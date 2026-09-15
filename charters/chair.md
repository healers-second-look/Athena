---
role_id: chair
charter_version: "1.0.0"
is_deterministic: true
kg_id: session_state_kg
jurisdiction:
  - session_management
  - quorum_verification
  - missing_data_audit
  - agenda_ordering
prohibited_claims:
  - systemic_therapy_option
  - molecular_variant_interpretation
  - histology
  - disease_burden
  - local_control_option
  - resectability
  - drug_interaction
  - trial_availability
  - symptom_burden
allowed_tools:
  - session_state_inspector
abstention_rules:
  - "Must abstain on any clinical question; the chair is deterministic and manages session structure only."
output_schema: SessionAgenda
---

# Board Seat: Chair (Deterministic)

## Purpose & Authority
The Chair is not a predictive model. It executes deterministic logic ensuring
quorum, completeness of baseline data, and session agenda management.

## Prohibitions
The Chair must never emit clinical findings, recommend regimens, or interpret pathology.
