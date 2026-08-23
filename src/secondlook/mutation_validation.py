"""Mutation notation parsing and canonical-sequence validation (Tier 2 Step 1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

import hgvs.parser
from bioutils.sequences import aa1_to_aa3
from hgvs.edit import AASub
from hgvs.exceptions import HGVSParseError

_SHORTHAND = re.compile(r"^([A-Z])(\d+)([A-Z])$")
_FUSION = re.compile(r"::|\bfusion\b|\bfus\b", re.IGNORECASE)
_SPLICE = re.compile(
    r"\bsplice\b|\bIVS\b|[cn]\.\d+\s*[+-]",
    re.IGNORECASE,
)

OUT_OF_SCOPE_MESSAGE = (
    "Tier 2 supports single amino-acid substitutions (missense) only. "
    "This variant type requires evidence-based review; no computational "
    "structural signal is available."
)

ValidationStatus = Literal["valid", "reference_mismatch", "unsupported_type"]
MutationType = Literal["missense", "insertion", "deletion", "frameshift", "fusion", "splice"]

_HGVS_TYPE_TO_MUTATION: dict[str, MutationType] = {
    "ins": "insertion",
    "dup": "insertion",
    "del": "deletion",
    "delins": "deletion",
    "fs": "frameshift",
}


@dataclass(frozen=True)
class ProteinSequence:
    accession: str
    sequence: str
    gene: str | None = None
    isoform_note: str | None = None


class SequenceProvider(Protocol):
    def fetch(self, identifier: str) -> ProteinSequence: ...


@dataclass(frozen=True)
class MutationValidationResult:
    status: ValidationStatus
    gene: str | None
    hgvs_normalized: str | None
    uniprot_accession: str | None
    isoform_note: str | None
    position: int | None
    reference_residue_expected: str | None
    reference_residue_actual: str | None
    mutation_type: MutationType | None
    error_message: str | None
    wildtype_sequence: str | None = None
    mutant_sequence: str | None = None


def normalize_protein_notation(notation: str) -> str:
    notation = notation.strip()
    match = _SHORTHAND.fullmatch(notation)
    if match is None:
        return notation
    ref, position, alt = match.groups()
    try:
        return f"p.{aa1_to_aa3(ref)}{position}{aa1_to_aa3(alt)}"
    except KeyError:
        # Matched the shorthand pattern (single uppercase letters) but one of them
        # isn't a real amino acid code (e.g. "Z175H" — Z is not a standard residue).
        # Fall through unchanged so the HGVS parser rejects it as invalid notation
        # (caught below, routed to the safe _unsupported() path) instead of crashing.
        return notation


def reference_mismatch_message(claimed: str, position: int, actual: str) -> str:
    return (
        f"Reference residue mismatch: notation claims {claimed} at position {position} "
        f"but canonical sequence has {actual}. This usually indicates a transcript/isoform "
        "numbering difference. Cannot proceed safely."
    )


def validate_mutation(
    identifier: str,
    mutation: str,
    *,
    sequence_provider: SequenceProvider | None = None,
) -> MutationValidationResult:
    raw = mutation.strip()
    preclassified = _classify_from_notation(raw)
    if preclassified is not None:
        return _unsupported(preclassified)

    if sequence_provider is None:
        from secondlook.uniprot import UniProtSequenceProvider

        sequence_provider = UniProtSequenceProvider()

    hgvs_normalized = normalize_protein_notation(raw)
    posedit_text = _strip_p_prefix(hgvs_normalized)
    parser = hgvs.parser.Parser()
    try:
        posedit = parser.parse_p_posedit(posedit_text)
    except HGVSParseError:
        return _unsupported()

    classified = _classify_from_hgvs_edit(posedit.edit)
    if classified is not None:
        return _unsupported(classified)

    if not isinstance(posedit.edit, AASub) or posedit.edit.alt in {"", "*"}:
        return _unsupported()

    position = int(posedit.pos.start.base)
    claimed_ref = str(posedit.pos.start.aa)
    alt = str(posedit.edit.alt)
    if claimed_ref == alt:
        return _unsupported()
    if not _is_valid_residue(claimed_ref) or not _is_valid_residue(alt):
        # The HGVS parser accepts any single uppercase letter as a residue code
        # without checking it's a real amino acid (e.g. "R175Z" parses "cleanly"
        # with alt="Z", which isn't a standard residue). Reject before it can
        # produce a fabricated mutant sequence containing a non-amino-acid letter.
        return _unsupported()

    protein = sequence_provider.fetch(identifier)
    if position < 1 or position > len(protein.sequence):
        return _mismatch(protein, hgvs_normalized, claimed_ref, position, "?")

    actual = protein.sequence[position - 1]
    if actual != claimed_ref:
        return _mismatch(protein, hgvs_normalized, claimed_ref, position, actual)

    mutant_sequence = protein.sequence[: position - 1] + alt + protein.sequence[position:]
    return MutationValidationResult(
        status="valid",
        gene=protein.gene,
        hgvs_normalized=hgvs_normalized,
        uniprot_accession=protein.accession,
        isoform_note=protein.isoform_note,
        position=position,
        reference_residue_expected=claimed_ref,
        reference_residue_actual=actual,
        mutation_type="missense",
        error_message=None,
        wildtype_sequence=protein.sequence,
        mutant_sequence=mutant_sequence,
    )


def _is_valid_residue(code: str) -> bool:
    try:
        aa1_to_aa3(code)
    except KeyError:
        return False
    return True


def _classify_from_notation(raw: str) -> MutationType | None:
    if _FUSION.search(raw):
        return "fusion"
    if _SPLICE.search(raw):
        return "splice"
    return None


def _classify_from_hgvs_edit(edit: object) -> MutationType | None:
    edit_type = getattr(edit, "type", None)
    if not isinstance(edit_type, str):
        return None
    return _HGVS_TYPE_TO_MUTATION.get(edit_type)


def _strip_p_prefix(notation: str) -> str:
    notation = notation.strip()
    if notation.startswith("p."):
        return notation[2:]
    return notation


def _mismatch(
    protein: ProteinSequence,
    hgvs_normalized: str,
    claimed_ref: str,
    position: int,
    actual: str,
) -> MutationValidationResult:
    return MutationValidationResult(
        status="reference_mismatch",
        gene=protein.gene,
        hgvs_normalized=hgvs_normalized,
        uniprot_accession=protein.accession,
        isoform_note=protein.isoform_note,
        position=position,
        reference_residue_expected=claimed_ref,
        reference_residue_actual=actual,
        mutation_type="missense",
        error_message=reference_mismatch_message(claimed_ref, position, actual),
    )


def _unsupported(mutation_type: MutationType | None = None) -> MutationValidationResult:
    return MutationValidationResult(
        status="unsupported_type",
        gene=None,
        hgvs_normalized=None,
        uniprot_accession=None,
        isoform_note=None,
        position=None,
        reference_residue_expected=None,
        reference_residue_actual=None,
        mutation_type=mutation_type,
        error_message=OUT_OF_SCOPE_MESSAGE,
    )
