"""Tests for Subsystem T: Role Charter & Capability Registry.

Validates that:
1. Every shipped role charter parses and adheres to the specifications from §1 / Issue #69.
2. Jurisdiction and prohibited claim sets are strictly disjoint.
3. Attempting to assign a tool producing prohibited or out-of-jurisdiction claims is refused.
4. Deterministic seats (Chair, Evidence Verifier) are marked non-model.
5. The registry enforces claim validation at runtime.
"""

from pathlib import Path

import pytest

from secondlook.board.charters import (
    CharterRegistry,
    CharterValidationError,
    ClaimKind,
    JurisdictionViolationError,
    RoleCharter,
    load_all_charters,
    load_charter,
)

CHARTERS_DIR = Path(__file__).resolve().parents[2] / "charters"

EXPECTED_ROLES = {
    "chair",
    "medical_oncologist",
    "molecular_pathologist",
    "anatomic_pathologist",
    "radiologist",
    "radiation_oncologist",
    "surgical_oncologist",
    "clinical_pharmacologist",
    "trials_access_officer",
    "supportive_palliative",
    "patient_navigator",
    "evidence_verifier",
}


class TestCharterDefinitions:
    def test_all_12_roles_exist_and_load(self):
        charters = load_all_charters(CHARTERS_DIR)
        assert set(charters.keys()) == EXPECTED_ROLES

    def test_chair_and_verifier_are_deterministic(self):
        charters = load_all_charters(CHARTERS_DIR)
        assert charters["chair"].is_deterministic is True
        assert charters["evidence_verifier"].is_deterministic is True

        clinical_roles = EXPECTED_ROLES - {"chair", "evidence_verifier"}
        for role in clinical_roles:
            assert (
                charters[role].is_deterministic is False
            ), f"Role '{role}' should not be marked deterministic"

    def test_each_charter_has_non_empty_disjoint_claims(self):
        charters = load_all_charters(CHARTERS_DIR)
        for role_id, charter in charters.items():
            assert charter.jurisdiction, f"Role '{role_id}' must have jurisdiction"
            assert charter.prohibited_claims, f"Role '{role_id}' must have prohibited claims"
            overlap = set(charter.jurisdiction) & set(charter.prohibited_claims)
            assert not overlap, f"Role '{role_id}' has overlapping claims: {overlap}"

    def test_medical_oncologist_prohibitions(self):
        charter = load_charter(CHARTERS_DIR / "medical_oncologist.md")
        assert ClaimKind.SYSTEMIC_THERAPY_OPTION in charter.jurisdiction
        assert ClaimKind.LINE_OF_THERAPY in charter.jurisdiction
        assert ClaimKind.HISTOLOGY in charter.prohibited_claims
        assert ClaimKind.DISEASE_BURDEN in charter.prohibited_claims
        assert ClaimKind.TRIAL_ELIGIBILITY_SCREEN in charter.prohibited_claims

    def test_molecular_pathologist_prohibitions(self):
        charter = load_charter(CHARTERS_DIR / "molecular_pathologist.md")
        assert ClaimKind.MOLECULAR_VARIANT_INTERPRETATION in charter.jurisdiction
        assert ClaimKind.ACTIONABILITY_CLASS in charter.jurisdiction
        assert ClaimKind.SYSTEMIC_THERAPY_OPTION in charter.prohibited_claims
        assert ClaimKind.TRIAL_AVAILABILITY in charter.prohibited_claims

    def test_patient_navigator_prohibitions(self):
        charter = load_charter(CHARTERS_DIR / "patient_navigator.md")
        assert ClaimKind.ACCESS_LOGISTICS in charter.jurisdiction
        assert ClaimKind.PATIENT_PREFERENCE in charter.jurisdiction
        assert ClaimKind.SYSTEMIC_THERAPY_OPTION in charter.prohibited_claims
        assert ClaimKind.HISTOLOGY in charter.prohibited_claims


class TestCharterValidationInvariants:
    def test_empty_jurisdiction_raises(self):
        with pytest.raises(CharterValidationError, match="must declare at least one claim"):
            RoleCharter(
                role_id="bad_role",
                charter_version="1.0.0",
                jurisdiction=(),
                prohibited_claims=(ClaimKind.HISTOLOGY,),
                kg_id="bad_kg",
                allowed_tools=(),
                abstention_rules=(),
            )

    def test_overlapping_claims_raises(self):
        with pytest.raises(CharterValidationError, match="overlapping jurisdiction and prohibited"):
            RoleCharter(
                role_id="conflict_role",
                charter_version="1.0.0",
                jurisdiction=(ClaimKind.HISTOLOGY, ClaimKind.SYSTEMIC_THERAPY_OPTION),
                prohibited_claims=(ClaimKind.HISTOLOGY,),
                kg_id="conflict_kg",
                allowed_tools=(),
                abstention_rules=(),
            )

    def test_tool_producing_prohibited_claims_raises(self):
        # pathology_report_inspector produces ClaimKind.HISTOLOGY
        with pytest.raises(JurisdictionViolationError, match="produces prohibited claims"):
            RoleCharter(
                role_id="rogue_role",
                charter_version="1.0.0",
                jurisdiction=(ClaimKind.SYSTEMIC_THERAPY_OPTION,),
                prohibited_claims=(ClaimKind.HISTOLOGY,),
                kg_id="rogue_kg",
                allowed_tools=("pathology_report_inspector",),
                abstention_rules=(),
            )

    def test_tool_producing_out_of_jurisdiction_claims_raises(self):
        # imaging_series_analyzer produces DISEASE_BURDEN, RECIST_RESPONSE, SITE_CONSTRAINT
        with pytest.raises(
            JurisdictionViolationError, match="produces claims outside jurisdiction"
        ):
            RoleCharter(
                role_id="limited_role",
                charter_version="1.0.0",
                jurisdiction=(
                    ClaimKind.DISEASE_BURDEN,
                ),  # Missing RECIST_RESPONSE and SITE_CONSTRAINT
                prohibited_claims=(),
                kg_id="limited_kg",
                allowed_tools=("imaging_series_analyzer",),
                abstention_rules=(),
            )


class TestCharterRegistry:
    def test_registry_claim_validation(self):
        charters = load_all_charters(CHARTERS_DIR)
        registry = CharterRegistry(charters)

        # Allowed
        registry.validate_claim("medical_oncologist", ClaimKind.SYSTEMIC_THERAPY_OPTION)
        registry.validate_claim("molecular_pathologist", ClaimKind.MOLECULAR_VARIANT_INTERPRETATION)

        # Prohibited
        with pytest.raises(JurisdictionViolationError, match="explicitly prohibited"):
            registry.validate_claim("molecular_pathologist", ClaimKind.SYSTEMIC_THERAPY_OPTION)

        # Outside jurisdiction
        with pytest.raises(JurisdictionViolationError, match="outside the jurisdiction"):
            registry.validate_claim("radiologist", ClaimKind.QUORUM_VERIFICATION)
