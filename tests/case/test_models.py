"""Schema-level checks. Offline -- no database needed, these inspect
`Base.metadata` directly.
"""

from secondlook.case.models import (
    ALL_MODELS,
    NO_PHI_COLUMN_PATTERN,
    Base,
)

# --- POLICY.md SS5.4: no PHI, enforced in code, not just convention ---------


def test_no_model_has_a_phi_shaped_column():
    """A schema-level test that fails CI if a disallowed column is added --
    exactly the enforcement issue #4 (Case Memory Store) requires. This is
    the one test in this file that must never be weakened or skipped to make
    a PR pass.
    """
    offending: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if NO_PHI_COLUMN_PATTERN.search(column.name):
                offending.append(f"{table.name}.{column.name}")

    assert not offending, (
        f"PHI-shaped column name(s) found: {offending}. "
        "See POLICY.md SS5.4 -- no name, DOB, MRN, or similar identifiers "
        "may be added to the Case Memory Store schema."
    )


def test_no_phi_pattern_actually_catches_known_bad_names():
    """The detector itself is tested, not just trusted -- a pattern that
    silently stopped matching would make the test above pass for the wrong
    reason.
    """
    for bad_name in ["patient_name", "date_of_birth", "mrn", "ssn", "email_address"]:
        assert NO_PHI_COLUMN_PATTERN.search(bad_name), f"Pattern should catch {bad_name!r}"

    for ok_name in ["cancer_type", "occurred_at", "evidence_class", "reason"]:
        assert not NO_PHI_COLUMN_PATTERN.search(ok_name), f"Pattern should NOT catch {ok_name!r}"


def test_all_five_tables_are_registered():
    """Five tables per IMPLEMENTATION_PLAN.md SS2.2 -- not four, not six."""
    table_names = {model.__tablename__ for model in ALL_MODELS}
    assert table_names == {"cases", "case_events", "questions", "findings", "decisions"}


def test_case_events_has_no_update_marker_and_is_append_only_by_convention():
    """The DB-level CHECK is a documented placeholder (see models.py's
    CaseEvent docstring) -- this test just confirms it's present as intended
    documentation, not that it's real enforcement. Real enforcement is
    tested in test_store.py against CaseStore's public interface.
    """
    case_events = Base.metadata.tables["case_events"]
    constraint_names = {c.name for c in case_events.constraints}
    assert "no_update" in constraint_names
