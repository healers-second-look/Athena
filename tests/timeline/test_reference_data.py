"""Tests for the Patient Timeline reference dataset (real osteosarc.com data,
checked in as JSON -- see reference_data.py's docstring for provenance)."""

from __future__ import annotations

from secondlook.timeline.reference_data import TimelineBundle, get_patient_timeline

EXPECTED_EVENT_CATEGORIES = {"Treatments", "Procedures", "Imaging"}


def test_returns_a_timeline_bundle():
    bundle = get_patient_timeline("any-patient-id")
    assert isinstance(bundle, TimelineBundle)


def test_events_are_scoped_to_the_three_requested_categories():
    """reference_data.py's docstring: events.tsv covers six categories, this
    module scopes to the three the Patient Timeline feature actually asks
    for (Treatments, Procedures, Imaging) -- assert that scoping happened,
    not "some events exist"."""
    bundle = get_patient_timeline("any-patient-id")
    categories = {e["category"] for e in bundle.events}
    assert categories == EXPECTED_EVENT_CATEGORIES


def test_every_event_has_a_date_and_something_identifying():
    """`title` is legitimately blank for some real source rows (17 of 284,
    all Imaging events where only subcategory/group was ever filled in --
    confirmed against the actual data, not assumed). The real invariant is
    that *something* identifies the event, not that title specifically is
    always present."""
    bundle = get_patient_timeline("any-patient-id")
    assert bundle.events
    for event in bundle.events:
        assert event["date"]
        assert event["title"] or event["subcategory"] or event["group"]


def test_every_data_track_is_non_empty():
    """A silently-empty track (e.g. a broken TSV conversion) should fail a
    test, not just render as an honest-looking empty section."""
    bundle = get_patient_timeline("any-patient-id")
    assert bundle.events
    assert bundle.mrd
    assert bundle.cytometry
    assert bundle.lab_results


def test_ignores_patient_id_today_by_design():
    """Documented, deliberate current behavior (reference_data.py's
    docstring) -- every patient_id returns the identical bundle until a real
    per-patient data source replaces this function's body. Pinning this so
    a future change to *actually* key on patient_id is a conscious edit to
    this test, not an accidental behavior change nobody notices."""
    a = get_patient_timeline("patient-a")
    b = get_patient_timeline("patient-b")
    assert a.as_dict() == b.as_dict()


def test_as_dict_round_trips_all_four_tracks():
    bundle = get_patient_timeline("any-patient-id")
    d = bundle.as_dict()
    assert set(d.keys()) == {"events", "mrd", "cytometry", "lab_results"}
