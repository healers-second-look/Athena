"""Caching and the gold-standard validation harness."""

import json

from test_pipeline import _run  # reuse the wired fake pipeline

from secondlook.cache import (
    cache_case,
    cache_key,
    load_payload,
    payload_is_stale,
    relabel_payload,
    save_payload,
    to_payload,
)
from secondlook.labeling import MethodCalibration
from secondlook.validation import (
    GOLD_STANDARD_CASES,
    HARD_REQUIRED_CONTROLS,
    PASS_THRESHOLD,
    build_report,
    render_markdown,
    score_case,
)

# --- Gold-standard case set ---------------------------------------------------


def test_all_nine_validation_plan_cases_are_present():
    assert len(GOLD_STANDARD_CASES) == 9


def test_case_set_matches_validation_plan_exactly():
    got = {(c.gene, c.mutation, c.drug) for c in GOLD_STANDARD_CASES}
    expected = {
        ("EGFR", "T790M", "gefitinib"),
        ("EGFR", "T790M", "osimertinib"),
        ("EGFR", "C797S", "osimertinib"),
        ("ABL1", "T315I", "imatinib"),
        ("KIT", "D816V", "imatinib"),
        ("KIT", "V560G", "imatinib"),
        ("BRAF", "V600E", "vemurafenib"),
        ("ALK", "G1202R", "crizotinib"),
        ("ALK", "I1171T", "crizotinib"),
    }
    assert got == expected


def test_expected_labels_follow_known_direction():
    for case in GOLD_STANDARD_CASES:
        if case.known_direction == "resistance":
            assert case.expected_label == "likely_reduced_binding"
        else:
            assert case.expected_label == "likely_retained_or_increased_binding"


def test_the_two_hard_required_controls_are_flagged():
    flagged = {
        (c.gene, c.mutation, c.drug) for c in GOLD_STANDARD_CASES if c.is_hard_required_control
    }
    assert flagged == {("BRAF", "V600E", "vemurafenib"), ("EGFR", "T790M", "osimertinib")}
    assert len(HARD_REQUIRED_CONTROLS) == 2


def test_pass_threshold_matches_the_precommitted_value():
    """validation-plan.md fixes this at 70%; it is not tunable after a run."""
    assert PASS_THRESHOLD == 0.70


# --- Scoring ------------------------------------------------------------------


def _payload(gene, mutation, drug, label, method="mCSM-lig", delta=-2.0):
    return {
        "gene": gene,
        "mutation": mutation,
        "status": "complete",
        "pipeline_version": "0.1.0",
        "results": [{"drug": drug, "label": label, "method": method, "delta_score": delta}],
        "failures": [],
    }


def test_correct_direction_scores_as_correct():
    case = next(c for c in GOLD_STANDARD_CASES if c.gene == "ABL1")
    outcome = score_case(case, _payload("ABL1", "T315I", "imatinib", "likely_reduced_binding"))
    assert outcome.correct is True
    assert outcome.confidently_wrong is False


def test_opposite_direction_is_confidently_wrong():
    case = next(c for c in GOLD_STANDARD_CASES if c.gene == "ABL1")
    outcome = score_case(
        case, _payload("ABL1", "T315I", "imatinib", "likely_retained_or_increased_binding")
    )
    assert outcome.correct is False
    assert outcome.confidently_wrong is True


def test_uncertain_is_wrong_but_not_confidently_wrong():
    """The distinction matters: 'uncertain' is honest, an inverted call is not."""
    case = next(c for c in GOLD_STANDARD_CASES if c.gene == "ABL1")
    outcome = score_case(case, _payload("ABL1", "T315I", "imatinib", "uncertain"))
    assert outcome.correct is False
    assert outcome.confidently_wrong is False


def test_missing_drug_scores_as_incorrect_not_skipped():
    case = next(c for c in GOLD_STANDARD_CASES if c.gene == "ABL1")
    outcome = score_case(case, _payload("ABL1", "T315I", "dasatinib", "likely_reduced_binding"))
    assert outcome.correct is False
    assert outcome.predicted_label is None
    assert "not among the generated candidates" in outcome.note


def test_drug_matching_is_case_insensitive():
    case = next(c for c in GOLD_STANDARD_CASES if c.gene == "ABL1")
    outcome = score_case(case, _payload("ABL1", "T315I", "IMATINIB", "likely_reduced_binding"))
    assert outcome.correct is True


# --- Report -------------------------------------------------------------------


def _all_correct_payloads():
    payloads = {}
    for case in GOLD_STANDARD_CASES:
        key = cache_key(case.gene, case.mutation)
        payload = payloads.setdefault(
            key,
            {
                "gene": case.gene,
                "mutation": case.mutation,
                "status": "complete",
                "pipeline_version": "0.1.0",
                "results": [],
                "failures": [],
            },
        )
        payload["results"].append(
            {
                "drug": case.drug,
                "label": case.expected_label,
                "method": "mCSM-lig",
                "delta_score": -2.0,
            }
        )
    return payloads


def test_all_correct_run_is_demo_ready():
    report = build_report(_all_correct_payloads())
    assert report.correct_count == 9
    assert report.pass_rate == 1.0
    assert report.is_demo_ready is True
    assert report.failed_hard_controls == []


def test_unscored_cases_count_against_the_pass_rate():
    """A case the pipeline could not score is wrong from the user's perspective."""
    report = build_report({})
    assert report.pass_rate == 0.0
    assert report.correct_count == 0
    assert report.is_demo_ready is False


def test_failing_a_hard_control_blocks_demo_readiness_even_at_high_pass_rate():
    payloads = _all_correct_payloads()
    braf = cache_key("BRAF", "V600E")
    payloads[braf]["results"][0]["label"] = "likely_reduced_binding"  # inverted
    report = build_report(payloads)
    assert report.pass_rate >= PASS_THRESHOLD  # 8/9 still clears 70%
    assert report.meets_pass_threshold is True
    assert len(report.failed_hard_controls) == 1
    assert report.is_demo_ready is False


def test_method_split_is_reported():
    report = build_report(_all_correct_payloads())
    assert report.method_split == {"mCSM-lig": 9}


def test_markdown_report_states_both_criteria_and_the_verdict():
    md = render_markdown(build_report(_all_correct_payloads()))
    assert "Demo-ready: YES" in md
    assert "Hard-required positive controls" in md
    assert "Pass rate" in md
    assert "| ABL1 | T315I | imatinib |" in md


def test_markdown_report_names_the_fallback_when_not_demo_ready():
    """The fallback text appears on a completed run that missed the bar.

    Uses a full run with wrong labels rather than an empty cache: an empty cache
    means "not yet run", which is a different report entirely.
    """
    payloads = _all_correct_payloads()
    for payload in payloads.values():
        for item in payload["results"]:
            item["label"] = "uncertain"
    md = render_markdown(build_report(payloads))
    assert "Demo-ready: NO" in md
    assert "binding pocket" in md
    assert "not a result to hide" in md


def test_markdown_does_not_claim_equivalent_method_confidence():
    md = render_markdown(build_report(_all_correct_payloads()))
    assert "not equivalent-confidence signals" in md


# --- Cache --------------------------------------------------------------------


def test_round_trip_through_the_cache(tmp_path):
    out = _run()
    cache_case(out, gene="TP53", mutation="R175H", cache_dir=tmp_path)
    loaded = load_payload("TP53", "R175H", cache_dir=tmp_path)
    assert loaded is not None
    assert loaded["results"][0]["drug"] == "Oxaliplatin"
    assert loaded["results"][0]["delta_score"] == -2.056


def test_loaded_payloads_are_always_marked_cached(tmp_path):
    """ui-flow.md Screen 3: a cached result must never render as live."""
    out = _run()
    payload = to_payload(out, gene="TP53", mutation="R175H")
    assert payload["cached"] is False
    save_payload(payload, cache_dir=tmp_path)
    assert load_payload("TP53", "R175H", cache_dir=tmp_path)["cached"] is True


def test_cached_flag_is_set_on_read_not_trusted_from_disk(tmp_path):
    out = _run()
    payload = to_payload(out, gene="TP53", mutation="R175H")
    payload["cached"] = False
    path = save_payload(payload, cache_dir=tmp_path)
    # Tamper with the file to claim it is live.
    tampered = json.loads(path.read_text())
    tampered["cached"] = False
    path.write_text(json.dumps(tampered))
    assert load_payload("TP53", "R175H", cache_dir=tmp_path)["cached"] is True


def test_missing_cache_entry_returns_none(tmp_path):
    assert load_payload("NOPE", "A1B", cache_dir=tmp_path) is None


def test_bulky_fields_are_excluded_from_the_cache():
    payload = to_payload(_run(), gene="TP53", mutation="R175H")
    assert "pdb_text" not in payload["structure"]
    assert "wildtype_sequence" not in payload["validation"]
    assert "mutant_sequence" not in payload["validation"]


def test_cached_payload_is_json_serializable():
    payload = to_payload(_run(), gene="TP53", mutation="R175H")
    assert json.loads(json.dumps(payload))["gene"] == "TP53"


def test_stale_pipeline_version_is_detected():
    payload = to_payload(_run(), gene="TP53", mutation="R175H")
    assert payload_is_stale(payload) is False
    payload["pipeline_version"] = "0.0.1-ancient"
    assert payload_is_stale(payload) is True


def test_cache_key_is_stable_across_notation_and_case():
    assert cache_key("tp53", "r175h") == cache_key("TP53", "R175H")
    assert cache_key("TP53", "p.R175H") == cache_key("TP53", "pR175H")


# --- Threshold sweep ----------------------------------------------------------


def test_relabeling_a_cached_payload_changes_the_label_without_rerunning():
    """The point of caching raw deltas: sweeping a cutoff costs nothing."""
    payload = to_payload(_run(), gene="TP53", mutation="R175H")
    assert payload["results"][0]["label"] == "likely_reduced_binding"

    strict = {
        "mCSM-lig": MethodCalibration(
            method="mCSM-lig",
            unit="log(affinity fold change)",
            orientation=1,
            reduced_at_or_below=-99.0,
            increased_at_or_above=99.0,
            confidence="moderate",
            accuracy_note="swept",
        )
    }
    relabeled = relabel_payload(payload, strict)
    assert relabeled["results"][0]["label"] == "uncertain"
    # Original payload untouched.
    assert payload["results"][0]["label"] == "likely_reduced_binding"


def test_relabeling_preserves_the_raw_delta():
    payload = to_payload(_run(), gene="TP53", mutation="R175H")
    relabeled = relabel_payload(payload, {})
    assert relabeled["results"][0]["delta_score"] == payload["results"][0]["delta_score"]


# --- "Not yet run" must never be reported as "ran and failed" ------------------
# An unrun harness rendered as a 0% pass rate would be a fabricated accuracy
# claim about the pipeline — the exact class of misleading output the project's
# "never state a fact you didn't compute" rule forbids.


def test_empty_cache_is_reported_as_not_yet_run_not_as_failure():
    md = render_markdown(build_report({}))
    assert "NOT YET RUN" in md
    assert "no measured pass rate and no verdict" in md
    assert "NOT MET" not in md
    assert "FAILED" not in md
    assert "Demo-ready: NO" not in md


def test_unrun_report_still_states_the_precommitted_criteria():
    """Stated for reference, explicitly marked as not evaluated."""
    md = render_markdown(build_report({}))
    assert "not yet evaluated" in md.lower()
    assert "70%" in md
    assert "BRAF V600E/vemurafenib" in md


def test_unrun_report_tells_you_how_to_run_it():
    assert "validation/run_gold_standard.py" in render_markdown(build_report({}))


def test_has_been_run_is_false_for_an_empty_cache():
    report = build_report({})
    assert report.has_been_run is False
    assert report.ran_count == 0
    assert report.is_demo_ready is False


def test_a_fully_run_report_is_not_flagged_as_unrun():
    report = build_report(_all_correct_payloads())
    assert report.has_been_run is True
    assert report.is_complete_run is True
    assert report.ran_count == 9
    assert "NOT YET RUN" not in render_markdown(report)


def test_partial_run_is_labelled_a_lower_bound_not_a_measured_rate():
    payloads = _all_correct_payloads()
    for key in list(payloads)[3:]:
        del payloads[key]
    report = build_report(payloads)
    assert report.has_been_run is True
    assert report.is_complete_run is False
    md = render_markdown(report)
    assert "Partial run" in md
    assert "lower bound" in md


def test_partial_run_does_not_claim_hard_controls_failed_when_unrun():
    """A control that never ran has not failed."""
    payloads = _all_correct_payloads()
    del payloads[cache_key("BRAF", "V600E")]
    md = render_markdown(build_report(payloads))
    assert "NOT YET RUN (BRAF V600E/vemurafenib)" in md
    assert "FAILED (BRAF" not in md


def test_a_genuinely_wrong_control_still_reports_as_failed():
    """The unrun carve-out must not mask a real inverted call."""
    payloads = _all_correct_payloads()
    payloads[cache_key("BRAF", "V600E")]["results"][0]["label"] = "likely_reduced_binding"
    md = render_markdown(build_report(payloads))
    assert "FAILED" in md
    assert "Demo-ready: NO" in md


def test_unrun_cases_are_marked_distinctly_in_the_table():
    payloads = _all_correct_payloads()
    del payloads[cache_key("ALK", "G1202R")]
    md = render_markdown(build_report(payloads))
    assert "· not run" in md


# --- A cached failure is not a cached result ---------------------------------


def test_cached_retryable_failure_is_rerun():
    """Otherwise a rate-limit blip freezes into the record permanently."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_gold_standard", "validation/run_gold_standard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    transient = {"results": [], "failures": [{"reason": "timeout", "retryable": True}]}
    permanent = {"results": [], "failures": [{"reason": "mismatch", "retryable": False}]}
    succeeded = {"results": [{"drug": "X"}], "failures": []}

    assert module.is_worth_rerunning(transient) is True
    assert module.is_worth_rerunning(permanent) is False
    assert module.is_worth_rerunning(succeeded) is False


def test_a_successful_run_is_never_rerun_even_with_a_stray_failure():
    """Partial success is still success — re-running would waste real docking time."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_gold_standard", "validation/run_gold_standard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    partial = {
        "results": [{"drug": "X"}],
        "failures": [{"reason": "timeout", "retryable": True}],
    }
    assert module.is_worth_rerunning(partial) is False


def test_failed_rerun_does_not_overwrite_a_good_cached_result():
    """A UniProt outage must not destroy measurements we already have.

    Learned the hard way: a re-run during a UniProt 500 replaced eight good
    proximity measurements with eight empty failure payloads.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_gold_standard", "validation/run_gold_standard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = open("validation/run_gold_standard.py").read()
    # The guard must sit before the write, not after.
    assert 'if not payload["results"] and existing and existing.get("results")' in source
    assert source.index("keeping the previous successful result") < source.index(
        "path = save_payload(payload"
    )
