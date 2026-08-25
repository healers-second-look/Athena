"""Offline tests for Subsystem M's server-rendered views.

No browser, no network, no fixtures beyond the committed JSON set. The two
tests that matter most here are structural rather than cosmetic:

* `TestComputedCardHasNoPlaceForACitation` asserts the *signature* of
  `_computed_card`, not just its output. IMPLEMENTATION_PLAN.md SS9.2 says
  the computed card must have no place for a citation, "not an empty one" --
  an output-only assertion would still pass after someone added an optional
  `citation_url=None` parameter, which is exactly the regression worth
  catching.
* `TestPerformanceBudget` asserts the gzipped byte budget from
  docs/performance-budget.md, so the budget fails CI when it is exceeded
  instead of aging into a document nobody re-measures.
"""

from __future__ import annotations

import gzip
import inspect
import re

import pytest

from secondlook.web import render
from secondlook.web.fixtures import load_all

TRIAL_EXISTS = "f0000000-0000-4000-8000-000000000031"
TRIAL_ELIGIBILITY = "f0000000-0000-4000-8000-000000000032"
SUPERSEDED = "f0000000-0000-4000-8000-000000000007"
REGULATORY = "f0000000-0000-4000-8000-000000000051"
CONTEXTUAL = "f0000000-0000-4000-8000-000000000061"

#: The first TCP congestion window is ~14.6 KB. A response that fits inside
#: it arrives in one round trip; one that does not costs an extra RTT, which
#: on the 400 ms link in the budget is a visible stall.
SSR_GZIP_BUDGET_BYTES = 14_000

#: Full URLs, not bare hostnames. A bare-hostname `in` check reads as URL
#: sanitization to a scanner and, more importantly, is a weaker assertion:
#: it passes on a citation rendered as inert text. Asserting the whole
#: href value checks the thing SS9 actually requires -- a clickable link.
TRIAL_CITATION = "https://clinicaltrials.gov/study/NCT03778229"
CIVIC_CITATION = "https://civicdb.org/evidence/1409"
PUBMED_CITATION = "https://pubmed.ncbi.nlm.nih.gov/25923549/"


@pytest.fixture(scope="module")
def data():
    return load_all()


@pytest.fixture(scope="module")
def degraded():
    """The same case with the trials lane timed out."""
    return load_all(degraded=True)


def _gz(html: str) -> int:
    return len(gzip.compress(html.encode("utf-8"), 9))


class TestComputedCardHasNoPlaceForACitation:
    def test_signature_accepts_no_citation_parameter(self):
        params = set(inspect.signature(render._computed_card).parameters)
        forbidden = {"citation_url", "citation_id", "url", "citation", "source_name"}
        assert not (params & forbidden), (
            "IMPLEMENTATION_PLAN.md SS9.2: the computed card must have no place "
            f"for a citation, not an empty one. Found {sorted(params & forbidden)}."
        )

    def test_passing_a_citation_is_a_typeerror(self):
        with pytest.raises(TypeError):
            render._computed_card("x", method="m", version="v", citation_url="https://example.org")

    def test_a_smuggled_citation_on_the_source_never_reaches_the_page(self, data):
        """Defence in depth: even if upstream data is wrong, the page is not."""
        finding = dict(data["findings"][TRIAL_ELIGIBILITY])
        finding["source"] = {
            **finding["source"],
            "citation_url": TRIAL_CITATION,
        }
        html = render.render_card(finding)
        assert TRIAL_CITATION not in html
        assert "href" not in html

    def test_computed_card_states_method_and_version(self, data):
        html = render.render_card(data["findings"][TRIAL_ELIGIBILITY])
        assert "signals.trial_matching.match_trial" in html
        assert "signals.trial_matching/1" in html

    def test_computed_card_is_dashed_not_solid(self, data):
        html = render.render_card(data["findings"][TRIAL_ELIGIBILITY])
        assert "card-computed" in html


class TestDocumentedCard:
    def test_citation_is_required_by_the_signature(self):
        sig = inspect.signature(render._documented_card)
        assert sig.parameters["citation_url"].default is inspect.Parameter.empty

    def test_citation_renders_clickable(self, data):
        html = render.render_card(data["findings"][TRIAL_EXISTS])
        assert f'href="{TRIAL_CITATION}"' in html
        assert "card-documented" in html

    def test_a_documented_finding_with_no_citation_url_raises(self, data):
        finding = dict(data["findings"][TRIAL_EXISTS])
        finding["source"] = {"kind": "documented", "name": "CIViC"}
        with pytest.raises(KeyError):
            render.render_card(finding)


class TestTheTrialPairRendersSideBySide:
    """Issue #46 emits two signals per matched trial. Reconciling them is M's job."""

    def test_both_cards_render_with_different_treatments(self, data):
        exists = render.render_card(data["findings"][TRIAL_EXISTS])
        bucket = render.render_card(data["findings"][TRIAL_ELIGIBILITY])
        assert "card-documented" in exists and "card-computed" not in exists
        assert "card-computed" in bucket and "card-documented" not in bucket
        # The documented half carries the registry link; the computed half
        # carries none at all. Same trial, two warrants, visibly different.
        assert f'href="{TRIAL_CITATION}"' in exists
        assert TRIAL_CITATION not in bucket
        assert "href=" not in bucket

    def test_the_bucket_carries_its_pre_screen_caveat(self, data):
        html = render.render_card(data["findings"][TRIAL_ELIGIBILITY])
        assert "not an eligibility determination" in html


class TestRegulatoryAndContextual:
    def test_regulatory_cites_the_instrument(self, data):
        html = render.render_card(data["findings"][REGULATORY])
        assert "card-regulatory" in html
        assert "CDSCO" in html

    def test_contextual_says_it_is_not_about_this_patient(self, data):
        html = render.render_card(data["findings"][CONTEXTUAL])
        assert "card-contextual" in html
        assert "not a finding about this patient" in html

    def test_an_unknown_evidence_class_raises_rather_than_rendering_generically(self):
        with pytest.raises(ValueError, match="unknown evidence class"):
            render.render_card({"evidence_class": "vibes", "claim": "x", "source": {}})


class TestCaveatsAreNeverDropped:
    def test_every_caveat_in_the_data_appears_on_the_page(self, data):
        finding = data["findings"][TRIAL_ELIGIBILITY]
        html = render.render_card(finding)
        for caveat in finding["caveats"]:
            # Escaped comparison: the em-dash and quotes survive escaping.
            assert render._e(caveat) in html


class TestChangeBanner:
    def test_every_change_is_rendered_not_a_sample(self, data):
        html = render.render_change_banner(data["changes"])
        for change in data["changes"]["changes"]:
            assert render._e(change["summary"]) in html

    def test_supersessions_use_literal_line_through(self, data):
        html = render.render_change_banner(data["changes"])
        assert "superseded-claim" in html
        css = render.load_stylesheet()
        assert re.search(r"\.superseded-claim\s*\{[^}]*text-decoration:\s*line-through", css), (
            "SS9.1 requires a literal text-decoration: line-through, not opacity "
            "or a colour change"
        )

    def test_supersession_note_and_trigger_are_both_shown(self, data):
        html = render.render_change_banner(data["changes"])
        assert "That is no longer true." in html
        assert "14 Feb sequencing" in html

    def test_an_empty_change_set_states_its_reason_rather_than_rendering_nothing(self):
        html = render.render_change_banner(
            {"changes": [], "supersessions": [], "unchanged_reason": "No tracked field changed."}
        )
        assert "No tracked field changed." in html


class TestFindingDetail:
    def test_provenance_chain_is_clickable_through_to_the_source(self, data):
        html = render.render_finding_detail(
            data["findings"]["f0000000-0000-4000-8000-000000000021"]
        )
        assert f'href="{CIVIC_CITATION}"' in html
        assert f'href="{PUBMED_CITATION}"' in html

    def test_review_buttons_work_without_javascript(self, data):
        html = render.render_finding_detail(data["findings"][TRIAL_EXISTS])
        assert 'method="post"' in html
        assert 'value="investigating"' in html and 'value="rejected"' in html

    def test_a_superseded_finding_is_struck_through_not_hidden(self, data):
        html = render.render_finding_detail(data["findings"][SUPERSEDED])
        assert "superseded-claim" in html
        assert "osimertinib-naive, EGFR-TKI candidate" in html

    def test_no_javascript_is_served(self, data):
        html = render.render_finding_detail(data["findings"][TRIAL_EXISTS])
        assert "<script" not in html.lower()
        assert "onclick" not in html.lower()

    def test_no_subresource_requests(self, data):
        """Zero external requests: no <link>, no <img>, no webfont."""
        html = render.render_finding_detail(data["findings"][TRIAL_EXISTS])
        assert "<link" not in html.lower()
        assert "<img" not in html.lower()
        assert "fonts.googleapis" not in html and "@import" not in html


class TestBrief:
    def test_suppressed_count_is_visible(self, data):
        html = render.render_brief(data["case"], data["changes"], data["queue"], data["findings"])
        assert "2 suppressed as already answered" in html

    def test_superseded_findings_are_printed_struck_through_not_omitted(self, data):
        html = render.render_brief(data["case"], data["changes"], data["queue"], data["findings"])
        assert "Superseded findings" in html
        assert "PD-L1 low; checkpoint monotherapy not indicated" in html

    def test_all_four_evidence_classes_render_distinctly(self, data):
        html = render.render_brief(data["case"], data["changes"], data["queue"], data["findings"])
        for klass in ("documented", "computed", "regulatory", "contextual"):
            assert f"card-{klass}" in html

    def test_print_stylesheet_expands_links_for_paper(self):
        css = render.load_stylesheet()
        assert "@media print" in css
        assert "a[href]::after" in css

    def test_open_questions_are_ordered_by_priority(self, data):
        html = render.render_brief(data["case"], data["changes"], data["queue"], data["findings"])
        progression = html.index("What resistance mechanisms are documented")
        biomarker = html.index("What does PD-L1 crossing")
        assert progression < biomarker, "priority 4 must precede priority 1"


class TestEscaping:
    def test_claims_are_escaped(self):
        html = render.render_card(
            {
                "evidence_class": "computed",
                "claim": "<script>alert(1)</script>",
                "source": {"method": "m", "version": "v"},
            }
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_none_renders_empty_not_the_word_none(self):
        assert render._e(None) == ""


class TestPerformanceBudget:
    """docs/performance-budget.md, asserted rather than aspired to."""

    def test_finding_detail_fits_one_congestion_window(self, data):
        size = _gz(render.render_finding_detail(data["findings"][TRIAL_ELIGIBILITY]))
        assert size <= SSR_GZIP_BUDGET_BYTES, f"{size} B gzipped exceeds the budget"

    def test_brief_fits_one_congestion_window(self, data):
        size = _gz(
            render.render_brief(data["case"], data["changes"], data["queue"], data["findings"])
        )
        assert size <= SSR_GZIP_BUDGET_BYTES, f"{size} B gzipped exceeds the budget"

    def test_the_budget_is_measured_on_a_real_page_not_an_empty_one(self, data):
        """Guards the guard: a budget that passes because the page is blank is not a budget."""
        html = render.render_brief(data["case"], data["changes"], data["queue"], data["findings"])
        assert len(html) > 8000
        assert html.count("card-") >= 6


class TestFixtures:
    def test_no_computed_fixture_carries_a_citation_field(self, data):
        for finding_id, finding in data["findings"].items():
            if finding["evidence_class"] != "computed":
                continue
            source = finding["source"]
            assert "citation_url" not in source, finding_id
            assert "citation_id" not in source, finding_id

    def test_a_missing_fixture_raises_rather_than_returning_empty(self, tmp_path):
        from secondlook.web.fixtures import _read

        with pytest.raises(FileNotFoundError, match="not found"):
            _read("case.json", tmp_path)


class TestDegradeNoticeSaysWhatFailedAndWhen:
    """#88: a failed lookup and an empty result must not render the same.

    Everything here is one assertion in different clothes -- the reader can
    tell, from the page alone, whether we looked and found nothing or never
    managed to look.
    """

    FAILURE = {
        "type": "failure",
        "tier": "1",
        "lane": "trials",
        "reason": "ClinicalTrials.gov lookup failed: connection timed out.",
        "retryable": True,
        "last_known_at": "2026-02-14T09:00:00Z",
    }

    def test_names_the_lane_and_the_reason(self):
        html = render.render_degrade_notice(self.FAILURE)
        assert "trials lookup unavailable" in html
        assert "connection timed out" in html

    def test_stale_data_is_dated_and_labelled_as_not_live(self):
        html = render.render_degrade_notice(self.FAILURE)
        assert "2026-02-14" in html
        assert "not a live result" in html

    def test_absent_cache_says_so_rather_than_implying_a_fresh_empty(self):
        html = render.render_degrade_notice({**self.FAILURE, "last_known_at": None})
        assert "No cached result is available" in html
        assert "not a live result" not in html

    def test_retryable_and_terminal_read_differently(self):
        retryable = render.render_degrade_notice(self.FAILURE)
        terminal = render.render_degrade_notice({**self.FAILURE, "retryable": False})
        assert "may succeed on retry" in retryable
        assert "will not succeed on retry" in terminal

    def test_a_lane_less_failure_still_renders(self):
        # docs/api-contracts.md: a failure object is always rendered. A
        # missing optional field is not grounds to drop the whole notice.
        html = render.render_degrade_notice({**self.FAILURE, "lane": None})
        assert "Lookup unavailable" in html
        assert "connection timed out" in html

    def test_only_an_absent_failure_renders_nothing(self):
        assert render.render_degrade_notice({}) == ""
        assert render.render_degrade_notice(None) == ""

    def test_the_reason_is_escaped(self):
        html = render.render_degrade_notice(
            {**self.FAILURE, "reason": '<img src=x onerror="alert(1)">'}
        )
        assert "<img" not in html
        assert "&lt;img" in html


class TestEmptyStateRefusesToRenderWithoutAReason:
    """The same move as `_computed_card` having no citation parameter: a rule
    that is only documented gets skipped, and a blank panel hides the skip."""

    @pytest.mark.parametrize("reason", [None, "", "   ", "\n"])
    def test_an_unexplained_empty_panel_cannot_be_rendered(self, reason):
        with pytest.raises(ValueError, match="requires a reason"):
            render.render_empty_state(reason)

    def test_the_reason_is_rendered_and_escaped(self):
        assert "0 candidates passed" in render.render_empty_state(
            "No trials matched — 0 candidates passed the gene/disease filter."
        )
        assert "&lt;b&gt;" in render.render_empty_state("<b>none</b>")


class TestBriefUnderDegrade:
    def _brief(self, bundle):
        return render.render_brief(
            bundle["case"], bundle["changes"], bundle["queue"], bundle["findings"]
        )

    def test_a_healthy_run_has_no_coverage_section(self, data):
        html = self._brief(data)
        assert "<h2>Coverage</h2>" not in html
        assert 'class="degraded"' not in html

    def test_a_failed_lane_is_reported_before_the_reader_can_stop_scrolling(self, degraded):
        html = self._brief(degraded)
        assert "<h2>Coverage</h2>" in html
        assert "trials lookup unavailable" in html
        # Above Current state, so a reader who stops after the first screen
        # still knows the run was incomplete.
        assert html.index("<h2>Coverage</h2>") < html.index("<h2>Current state</h2>")

    def test_the_unanswered_question_is_listed_and_marked_not_dispatched(self, degraded):
        html = self._brief(degraded)
        assert "Are there recruiting trials matching EGFR T790M?" in html
        assert "was not dispatched" in html

    def test_questions_in_healthy_lanes_are_not_marked(self, degraded):
        # Exactly one question is in the failed lane; the rest must read as
        # normal open work, or the label means nothing.
        assert self._brief(degraded).count("was not dispatched") == 1

    def test_local_content_still_renders_with_the_lane_down(self, degraded):
        # III.3's actual requirement: only live external lookups degrade. The
        # case record, the change banner and the curated-KB findings are all
        # local and must be unaffected.
        html = self._brief(degraded)
        assert "Lung adenocarcinoma" in html
        assert "Superseded findings" in html
        for klass in ("documented", "computed", "regulatory", "contextual"):
            assert f"card-{klass}" in html


class TestNoSilentBlankPanels:
    def test_an_empty_queue_says_why_instead_of_rendering_nothing(self, data):
        empty = {"counts": {"open": 0, "suppressed": 0}, "open": [], "suppressed": []}
        html = render.render_brief(data["case"], data["changes"], empty, data["findings"])
        assert "No open questions" in html
        assert 'class="empty-state"' in html

    def test_no_active_findings_says_why(self, data):
        superseded_only = {
            k: v for k, v in data["findings"].items() if v.get("status") == "superseded"
        }
        assert superseded_only, "fixture set must contain a superseded finding"
        html = render.render_brief(data["case"], data["changes"], data["queue"], superseded_only)
        assert "No active findings" in html
        assert "superseded" in html


class TestTheTwoQueueFixturesDifferOnlyInTheDegrade:
    """Guards the contrast the whole feature rests on. If the fixtures drift
    apart in other ways, `TestBriefUnderDegrade` stops proving anything."""

    def test_same_case_same_questions(self, data, degraded):
        healthy_q, degraded_q = data["queue"], degraded["queue"]
        assert healthy_q["case_id"] == degraded_q["case_id"]
        assert [q["id"] for q in healthy_q["open"]] == [q["id"] for q in degraded_q["open"]]
        assert healthy_q["counts"] == degraded_q["counts"]

    def test_the_healthy_set_states_that_nothing_failed(self, data):
        # Present and empty, not absent: "we checked, nothing failed" is a
        # fact the route always states.
        assert data["queue"]["failures"] == []

    def test_the_failed_lane_lost_exactly_its_own_findings(self, data, degraded):
        healthy = {q["id"]: q for q in data["queue"]["open"]}
        failed_lane = degraded["queue"]["failures"][0]["lane"]
        for q in degraded["queue"]["open"]:
            if q["lane"] == failed_lane:
                assert q["finding_ids"] == []
                assert healthy[q["id"]]["finding_ids"], "the contrast needs a non-empty baseline"
            else:
                assert q["finding_ids"] == healthy[q["id"]]["finding_ids"]


class TestDevServerDoesNotReflectUnescapedInput:
    """The 404s echo a path segment back; `page()` composes markup, it does not
    escape it. Echoing unescaped would be reflected XSS in the dev harness."""

    def _handler(self):
        from secondlook.web.server import Handler

        sent = {}

        class Fake(Handler):
            def __init__(self):  # bypass BaseHTTPRequestHandler's socket setup
                pass

            def _send(self, status, html):
                sent["status"] = status
                sent["html"] = html

        return Fake(), sent

    def test_a_script_tag_in_the_path_is_escaped(self):
        handler, sent = self._handler()
        handler._error(404, "No fixture case with id <script>alert(1)</script>.")
        assert "<script>" not in sent["html"]
        assert "&lt;script&gt;" in sent["html"]
        assert sent["status"] == 404

    def test_the_route_help_text_survives_escaping_readably(self):
        handler, sent = self._handler()
        handler._error(404, "Routes are /cases/<id>/brief.")
        assert "/cases/&lt;id&gt;/brief" in sent["html"]
