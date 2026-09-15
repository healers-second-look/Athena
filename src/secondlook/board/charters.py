"""Role Charter & Capability Registry.

Subsystem T (Issue #75, P0).

Role behavior in a multi-agent tumor board must be a reviewed, versioned artifact,
not an unconstrained LLM prompt. Each role has:
1. A jurisdiction (what clinical/operational claims it may emit)
2. An evidence base (the exact, isolated KG it is permitted to read)
3. A prohibition list (claims it must refuse to make)
4. An allowed tool list (verified at startup against jurisdiction)

If any role's declared tools or emitted claims exceed its jurisdiction, or overlap
with its prohibited list, the registry refuses startup immediately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class ClaimKind(StrEnum):
    """Granular taxonomy of claims made across tumor board seats."""

    # Operational / Session
    SESSION_MANAGEMENT = "session_management"
    QUORUM_VERIFICATION = "quorum_verification"
    MISSING_DATA_AUDIT = "missing_data_audit"
    AGENDA_ORDERING = "agenda_ordering"

    # Medical Oncology
    SYSTEMIC_THERAPY_OPTION = "systemic_therapy_option"
    LINE_OF_THERAPY = "line_of_therapy"
    SEQUENCING = "sequencing"
    EXHAUSTION_STATUS = "exhaustion_status"

    # Molecular Pathology
    MOLECULAR_VARIANT_INTERPRETATION = "molecular_variant_interpretation"
    ACTIONABILITY_CLASS = "actionability_class"
    ASSAY_ADEQUACY = "assay_adequacy"
    VAF_PURITY_CAVEAT = "vaf_purity_caveat"

    # Anatomic Pathology
    HISTOLOGY = "histology"
    TUMOR_GRADE = "tumor_grade"
    IHC_STAINING = "ihc_staining"
    BIOMARKER_ADEQUACY = "biomarker_adequacy"

    # Radiology
    DISEASE_BURDEN = "disease_burden"
    RECIST_RESPONSE = "recist_response"
    SITE_CONSTRAINT = "site_constraint"

    # Radiation Oncology
    LOCAL_CONTROL_OPTION = "local_control_option"
    RADIATION_DOSE_CONSTRAINT = "radiation_dose_constraint"
    FIELD_FEASIBILITY = "field_feasibility"

    # Surgical Oncology
    RESECTABILITY = "resectability"
    SURGICAL_APPROACH = "surgical_approach"
    NEOADJUVANT_SEQUENCING = "neoadjuvant_sequencing"

    # Clinical Pharmacology
    DRUG_INTERACTION = "drug_interaction"
    ORGAN_FUNCTION_DOSING = "organ_function_dosing"
    CUMULATIVE_DOSE_CAP = "cumulative_dose_cap"

    # Trials & Access
    TRIAL_AVAILABILITY = "trial_availability"
    TRIAL_ELIGIBILITY_SCREEN = "trial_eligibility_screen"
    ACCESS_PATHWAY_ROUTE = "access_pathway_route"

    # Supportive & Palliative Care
    SYMPTOM_BURDEN = "symptom_burden"
    PERFORMANCE_STATUS_TRAJECTORY = "performance_status_trajectory"
    GOALS_OF_CARE = "goals_of_care"

    # Patient Navigator
    ACCESS_LOGISTICS = "access_logistics"
    PATIENT_PREFERENCE = "patient_preference"
    FINANCIAL_TOXICITY = "financial_toxicity"

    # Evidence Verifier
    CITATION_VERIFICATION = "citation_verification"
    RETRACTION_STATUS = "retraction_status"
    IDENTITY_RESOLUTION = "identity_resolution"


class CharterValidationError(ValueError):
    """A role charter is malformed or internally contradictory."""


class JurisdictionViolationError(PermissionError):
    """An agent's tools or requested claims exceed its jurisdiction."""


# Known tools and the claim kinds they are capable of producing
TOOL_CAPABILITIES: dict[str, frozenset[ClaimKind]] = {
    "session_state_inspector": frozenset(
        {
            ClaimKind.SESSION_MANAGEMENT,
            ClaimKind.QUORUM_VERIFICATION,
            ClaimKind.MISSING_DATA_AUDIT,
            ClaimKind.AGENDA_ORDERING,
        }
    ),
    "guideline_kb_query": frozenset(
        {
            ClaimKind.SYSTEMIC_THERAPY_OPTION,
            ClaimKind.LINE_OF_THERAPY,
            ClaimKind.SEQUENCING,
            ClaimKind.EXHAUSTION_STATUS,
        }
    ),
    "molecular_kb_query": frozenset(
        {
            ClaimKind.MOLECULAR_VARIANT_INTERPRETATION,
            ClaimKind.ACTIONABILITY_CLASS,
            ClaimKind.ASSAY_ADEQUACY,
            ClaimKind.VAF_PURITY_CAVEAT,
        }
    ),
    "pathology_report_inspector": frozenset(
        {
            ClaimKind.HISTOLOGY,
            ClaimKind.TUMOR_GRADE,
            ClaimKind.IHC_STAINING,
            ClaimKind.BIOMARKER_ADEQUACY,
        }
    ),
    "imaging_series_analyzer": frozenset(
        {
            ClaimKind.DISEASE_BURDEN,
            ClaimKind.RECIST_RESPONSE,
            ClaimKind.SITE_CONSTRAINT,
        }
    ),
    "radiation_protocol_calc": frozenset(
        {
            ClaimKind.LOCAL_CONTROL_OPTION,
            ClaimKind.RADIATION_DOSE_CONSTRAINT,
            ClaimKind.FIELD_FEASIBILITY,
        }
    ),
    "surgical_criteria_evaluator": frozenset(
        {
            ClaimKind.RESECTABILITY,
            ClaimKind.SURGICAL_APPROACH,
            ClaimKind.NEOADJUVANT_SEQUENCING,
        }
    ),
    "pharmacology_ddi_lookup": frozenset(
        {
            ClaimKind.DRUG_INTERACTION,
            ClaimKind.ORGAN_FUNCTION_DOSING,
            ClaimKind.CUMULATIVE_DOSE_CAP,
        }
    ),
    "clinical_trials_matcher": frozenset(
        {
            ClaimKind.TRIAL_AVAILABILITY,
            ClaimKind.TRIAL_ELIGIBILITY_SCREEN,
            ClaimKind.ACCESS_PATHWAY_ROUTE,
        }
    ),
    "symptom_trajectory_evaluator": frozenset(
        {
            ClaimKind.SYMPTOM_BURDEN,
            ClaimKind.PERFORMANCE_STATUS_TRAJECTORY,
            ClaimKind.GOALS_OF_CARE,
        }
    ),
    "navigation_logistics_planner": frozenset(
        {
            ClaimKind.ACCESS_LOGISTICS,
            ClaimKind.PATIENT_PREFERENCE,
            ClaimKind.FINANCIAL_TOXICITY,
        }
    ),
    "citation_gate_verifier": frozenset(
        {
            ClaimKind.CITATION_VERIFICATION,
            ClaimKind.RETRACTION_STATUS,
            ClaimKind.IDENTITY_RESOLUTION,
        }
    ),
}


@dataclass(frozen=True)
class RoleCharter:
    """Immutable specification of a single tumor board role's authority."""

    role_id: str
    charter_version: str
    jurisdiction: tuple[ClaimKind, ...]
    prohibited_claims: tuple[ClaimKind, ...]
    kg_id: str
    allowed_tools: tuple[str, ...]
    abstention_rules: tuple[str, ...]
    is_deterministic: bool = False
    output_schema: str = "Finding"

    def __post_init__(self) -> None:
        if not self.role_id:
            raise CharterValidationError("role_id cannot be empty")
        if not self.charter_version:
            raise CharterValidationError("charter_version must be specified")
        if not self.jurisdiction:
            raise CharterValidationError(
                f"Role '{self.role_id}' must declare at least one claim in jurisdiction"
            )

        # Invariant 1: Jurisdiction and prohibited claims must be strictly disjoint
        overlap = set(self.jurisdiction) & set(self.prohibited_claims)
        if overlap:
            names = sorted(c.value for c in overlap)
            raise CharterValidationError(
                f"Role '{self.role_id}' has overlapping jurisdiction and prohibited claims: {names}"
            )

        # Invariant 2: Allowed tools must not produce prohibited claims
        prohibited_set = set(self.prohibited_claims)
        jurisdiction_set = set(self.jurisdiction)
        for tool in self.allowed_tools:
            caps = TOOL_CAPABILITIES.get(tool)
            if caps is None:
                continue
            prohibited_produced = caps & prohibited_set
            if prohibited_produced:
                names = sorted(c.value for c in prohibited_produced)
                msg = (
                    f"Tool '{tool}' granted to role '{self.role_id}' "
                    f"produces prohibited claims: {names}"
                )
                raise JurisdictionViolationError(msg)
            outside_jurisdiction = caps - jurisdiction_set
            if outside_jurisdiction:
                names = sorted(c.value for c in outside_jurisdiction)
                msg = (
                    f"Tool '{tool}' granted to role '{self.role_id}' "
                    f"produces claims outside jurisdiction: {names}"
                )
                raise JurisdictionViolationError(msg)


def parse_charter_markdown(content: str) -> RoleCharter:
    """Parse a Markdown charter file with YAML frontmatter."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not match:
        raise CharterValidationError(
            "Charter file must begin with YAML frontmatter delimited by '---'"
        )

    raw_meta = match.group(1)
    try:
        meta: dict[str, Any] = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError as exc:
        raise CharterValidationError(f"Failed to parse YAML frontmatter: {exc}") from exc

    role_id = str(meta.get("role_id", ""))
    version = str(meta.get("charter_version", "1.0.0"))
    kg_id = str(meta.get("kg_id", f"{role_id}_kg"))
    is_det = bool(meta.get("is_deterministic", False))
    output_schema = str(meta.get("output_schema", "Finding"))

    jurisdiction = tuple(ClaimKind(k) for k in meta.get("jurisdiction", ()))
    prohibited = tuple(ClaimKind(k) for k in meta.get("prohibited_claims", ()))
    tools = tuple(str(t) for t in meta.get("allowed_tools", ()))
    abstentions = tuple(str(a) for a in meta.get("abstention_rules", ()))

    return RoleCharter(
        role_id=role_id,
        charter_version=version,
        jurisdiction=jurisdiction,
        prohibited_claims=prohibited,
        kg_id=kg_id,
        allowed_tools=tools,
        abstention_rules=abstentions,
        is_deterministic=is_det,
        output_schema=output_schema,
    )


def load_charter(file_path: Path | str) -> RoleCharter:
    """Load a role charter from a markdown file path."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Charter file not found: {p}")
    content = p.read_text(encoding="utf-8")
    return parse_charter_markdown(content)


def load_all_charters(charters_dir: Path | str) -> dict[str, RoleCharter]:
    """Load all role charters from a directory, indexed by role_id."""
    d = Path(charters_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"Charters directory not found: {d}")

    charters: dict[str, RoleCharter] = {}
    for md_file in sorted(d.glob("*.md")):
        charter = load_charter(md_file)
        if charter.role_id in charters:
            raise CharterValidationError(
                f"Duplicate role_id '{charter.role_id}' found in {md_file.name}"
            )
        charters[charter.role_id] = charter

    return charters


class CharterRegistry:
    """Central registry of validated board role charters."""

    def __init__(self, charters: dict[str, RoleCharter] | None = None) -> None:
        self._charters: dict[str, RoleCharter] = dict(charters or {})

    def register(self, charter: RoleCharter) -> None:
        if charter.role_id in self._charters:
            raise CharterValidationError(f"Role '{charter.role_id}' is already registered")
        self._charters[charter.role_id] = charter

    def get(self, role_id: str) -> RoleCharter:
        if role_id not in self._charters:
            raise KeyError(f"No role charter registered for '{role_id}'")
        return self._charters[role_id]

    def all_roles(self) -> tuple[str, ...]:
        return tuple(self._charters.keys())

    def validate_claim(self, role_id: str, claim_kind: ClaimKind) -> None:
        """Verify that a role is legally permitted to make a claim."""
        charter = self.get(role_id)
        if claim_kind in charter.prohibited_claims:
            raise JurisdictionViolationError(
                f"Role '{role_id}' is explicitly prohibited from emitting '{claim_kind.value}'"
            )
        if claim_kind not in charter.jurisdiction:
            raise JurisdictionViolationError(
                f"Claim '{claim_kind.value}' is outside the jurisdiction of role '{role_id}'"
            )
