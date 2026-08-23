"""Step 6 threshold labeling."""

import pytest

from secondlook.labeling import (
    BINDING_LABELS,
    DOCKING_CALIBRATION,
    MCSM_LIG_CALIBRATION,
    MethodCalibration,
    calibration_for,
    label_binding_delta,
)

# --- The sign-convention trap ------------------------------------------------
# mCSM-lig and docking report reduced binding with OPPOSITE signs. These are the
# most important tests in this module: a regression here silently inverts the
# label on every docking-scored candidate, which per tier2-implementation-spec.md
# §1.3 item 6 is most real traffic.


def test_mcsm_negative_delta_is_reduced_binding():
    """mCSM-lig labels a negative affinity change 'Destabilizing' (verified live on 2Z4O/D30N)."""
    result = label_binding_delta(-2.056, "mCSM-lig")
    assert result.label == "likely_reduced_binding"


def test_mcsm_positive_delta_is_retained_or_increased():
    result = label_binding_delta(2.0, "mCSM-lig")
    assert result.label == "likely_retained_or_increased_binding"


def test_docking_positive_delta_is_reduced_binding():
    """Vina delta is mutant minus wildtype; a higher (less negative) mutant score binds worse."""
    result = label_binding_delta(2.0, "docking")
    assert result.label == "likely_reduced_binding"


def test_docking_negative_delta_is_retained_or_increased():
    result = label_binding_delta(-2.0, "docking")
    assert result.label == "likely_retained_or_increased_binding"


def test_same_numeric_delta_labels_oppositely_across_methods():
    """The explicit statement of the trap: identical numbers, opposite meanings."""
    mcsm = label_binding_delta(-2.0, "mCSM-lig")
    docking = label_binding_delta(-2.0, "docking")
    assert mcsm.label == "likely_reduced_binding"
    assert docking.label == "likely_retained_or_increased_binding"
    assert mcsm.label != docking.label


# --- Label-set contract ------------------------------------------------------


@pytest.mark.parametrize("method", ["mCSM-lig", "docking"])
@pytest.mark.parametrize(
    "delta",
    [-1e9, -100.0, -2.0, -0.5, -0.05, 0.0, 0.05, 0.5, 2.0, 100.0, 1e9],
)
def test_only_ever_emits_declared_labels(method, delta):
    """Post-condition on the real contract, not on current behavior.

    Asserts against BINDING_LABELS itself rather than a hand-copied list, so the
    test cannot be quietly relaxed to accommodate a new escaping value — the
    RareCure `clamp_weights` failure mode.
    """
    result = label_binding_delta(delta, method)
    assert result.label in BINDING_LABELS
    assert len(BINDING_LABELS) == 3


@pytest.mark.parametrize("method", ["mCSM-lig", "docking"])
def test_zero_delta_is_uncertain(method):
    assert label_binding_delta(0.0, method).label == "uncertain"


@pytest.mark.parametrize("method", ["mCSM-lig", "docking"])
def test_boundary_values_are_inclusive_and_deterministic(method):
    calibration = calibration_for(method)
    # Convert a canonical-scale threshold back to a raw delta for this method.
    reduced_raw = calibration.reduced_at_or_below * calibration.orientation
    increased_raw = calibration.increased_at_or_above * calibration.orientation
    assert label_binding_delta(reduced_raw, method).label == "likely_reduced_binding"
    assert (
        label_binding_delta(increased_raw, method).label == "likely_retained_or_increased_binding"
    )


# --- Method-aware confidence -------------------------------------------------


def test_docking_and_mcsm_do_not_share_confidence_framing():
    """tier2-implementation-spec.md §5 deliverable 1 requires these differ."""
    mcsm = label_binding_delta(-2.056, "mCSM-lig")
    docking = label_binding_delta(2.0, "docking")
    assert mcsm.label == docking.label == "likely_reduced_binding"
    assert mcsm.confidence != docking.confidence
    assert mcsm.accuracy_note != docking.accuracy_note


def test_docking_accuracy_note_does_not_claim_a_correlation_figure():
    """validation-plan.md: cite real accuracy figures, not assumed ones.

    mCSM-lig has a published rho; Vina has none for this task. The docking note
    must not borrow one.
    """
    note = label_binding_delta(2.0, "docking").accuracy_note
    assert "rho" not in note.lower()
    assert "0.67" not in note


def test_mcsm_accuracy_note_cites_its_real_published_figure():
    note = label_binding_delta(-2.056, "mCSM-lig").accuracy_note
    assert "0.67" in note
    assert "2016" in note


# --- Heuristic / calibration honesty -----------------------------------------


@pytest.mark.parametrize("method", ["mCSM-lig", "docking"])
def test_every_label_carries_the_internal_heuristic_note(method):
    result = label_binding_delta(1.0, method)
    assert "not a validated clinical threshold" in result.heuristic_note


@pytest.mark.parametrize("method", ["mCSM-lig", "docking"])
def test_uncalibrated_labels_say_so(method):
    """Until the gold-standard run happens, no caller may mistake this for calibrated."""
    result = label_binding_delta(1.0, method)
    assert result.calibration_status == "provisional"
    assert "has not yet been calibrated" in result.heuristic_note


@pytest.mark.parametrize("method", ["mCSM-lig", "docking"])
def test_units_are_reported_and_method_specific(method):
    result = label_binding_delta(1.0, method)
    assert result.unit
    assert result.unit == calibration_for(method).unit


def test_the_two_methods_report_different_units():
    assert MCSM_LIG_CALIBRATION.unit != DOCKING_CALIBRATION.unit


# --- Calibration override (used by the validation sweep) ---------------------


def test_calibration_override_changes_the_label_without_module_mutation():
    strict = MethodCalibration(
        method="mCSM-lig",
        unit="log(affinity fold change)",
        orientation=1,
        reduced_at_or_below=-5.0,
        increased_at_or_above=5.0,
        confidence="moderate",
        accuracy_note="swept",
    )
    default = label_binding_delta(-2.056, "mCSM-lig")
    swept = label_binding_delta(-2.056, "mCSM-lig", calibration=strict)
    assert default.label == "likely_reduced_binding"
    assert swept.label == "uncertain"
    # Module default is untouched by the override.
    assert label_binding_delta(-2.056, "mCSM-lig").label == "likely_reduced_binding"


def test_unknown_method_raises_rather_than_borrowing_a_calibration():
    """Units differ per method, so silently defaulting would be meaningless."""
    with pytest.raises(KeyError):
        calibration_for("some-future-scorer")


def test_canonical_delta_normalizes_both_methods_to_one_scale():
    """Negative canonical delta means reduced binding, whichever method produced it."""
    assert MCSM_LIG_CALIBRATION.canonical_delta(-2.0) < 0
    assert DOCKING_CALIBRATION.canonical_delta(2.0) < 0
    assert MCSM_LIG_CALIBRATION.canonical_delta(2.0) > 0
    assert DOCKING_CALIBRATION.canonical_delta(-2.0) > 0
