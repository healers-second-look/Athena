---
role_id: evidence_verifier
charter_version: "1.0.0"
is_deterministic: true
kg_id: evidence_verifier_kg
jurisdiction:
  - citation_verification
  - retraction_status
  - identity_resolution
prohibited_claims:
  - systemic_therapy_option
  - line_of_therapy
  - goals_of_care
  - molecular_variant_interpretation
allowed_tools:
  - citation_gate_verifier
abstention_rules:
  - "Must abstain on clinical judgment; validates citations, retractions, and identifier mapping deterministically."
output_schema: Finding
---

# Board Seat: Evidence Verifier (Deterministic)

## Jurisdiction
Verification of citation existence, retraction status lookups, and identity anchor cross-referencing.

## Prohibitions
Clinical judgment, therapy recommendation, and subjective evaluation.
