"""AlphaMissense pathogenicity lookup via Ensembl VEP (Tier 2 Step 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from secondlook.ensembl import EnsemblError
from secondlook.mutation_validation import MutationValidationResult

AlphaMissenseClass = Literal["likely_benign", "ambiguous", "likely_pathogenic"]
NO_SCORE_NOTE = "no AlphaMissense score available"

CODON_TABLE = {
    "TTT": "F",
    "TTC": "F",
    "TTA": "L",
    "TTG": "L",
    "TCT": "S",
    "TCC": "S",
    "TCA": "S",
    "TCG": "S",
    "TAT": "Y",
    "TAC": "Y",
    "TAA": "*",
    "TAG": "*",
    "TGT": "C",
    "TGC": "C",
    "TGA": "*",
    "TGG": "W",
    "CTT": "L",
    "CTC": "L",
    "CTA": "L",
    "CTG": "L",
    "CCT": "P",
    "CCC": "P",
    "CCA": "P",
    "CCG": "P",
    "CAT": "H",
    "CAC": "H",
    "CAA": "Q",
    "CAG": "Q",
    "CGT": "R",
    "CGC": "R",
    "CGA": "R",
    "CGG": "R",
    "ATT": "I",
    "ATC": "I",
    "ATA": "I",
    "ATG": "M",
    "ACT": "T",
    "ACC": "T",
    "ACA": "T",
    "ACG": "T",
    "AAT": "N",
    "AAC": "N",
    "AAA": "K",
    "AAG": "K",
    "AGT": "S",
    "AGC": "S",
    "AGA": "R",
    "AGG": "R",
    "GTT": "V",
    "GTC": "V",
    "GTA": "V",
    "GTG": "V",
    "GCT": "A",
    "GCC": "A",
    "GCA": "A",
    "GCG": "A",
    "GAT": "D",
    "GAC": "D",
    "GAA": "E",
    "GAG": "E",
    "GGT": "G",
    "GGC": "G",
    "GGA": "G",
    "GGG": "G",
}


class TranscriptResolver(Protocol):
    def resolve_mane_select(self, gene_symbol: str) -> str: ...
    def fetch_cds(self, transcript_id: str) -> str: ...


class VepClient(Protocol):
    def lookup_hgvs(self, transcript_id: str, hgvs: str) -> list[dict]: ...


@dataclass(frozen=True)
class AlphaMissenseResult:
    status: Literal["scored", "unavailable"]
    am_pathogenicity: float | None
    am_class: AlphaMissenseClass | None
    ensembl_am_class: str | None
    transcript_id: str | None
    hgvs_c: str | None
    note: str | None = None


def classify_alphamissense(score: float) -> AlphaMissenseClass:
    if score <= 0.333:
        return "likely_benign"
    if score <= 0.564:
        return "ambiguous"
    return "likely_pathogenic"


def extract_alphamissense(vep_payload: list[dict], transcript_id: str) -> dict | None:
    wanted = _unversioned(transcript_id)
    for record in vep_payload:
        for consequence in record.get("transcript_consequences") or []:
            if _unversioned(str(consequence.get("transcript_id") or "")) != wanted:
                continue
            alphamissense = consequence.get("alphamissense")
            if not isinstance(alphamissense, dict) or "am_pathogenicity" not in alphamissense:
                return None
            return {
                "am_pathogenicity": float(alphamissense["am_pathogenicity"]),
                "am_class": alphamissense.get("am_class"),
                "transcript_id": consequence.get("transcript_id"),
                "cds_start": consequence.get("cds_start"),
                "codons": consequence.get("codons"),
            }
    return None


def protein_sub_to_hgvs_c(cds: str, position: int, ref_aa: str, alt_aa: str) -> str:
    cds = cds.upper().replace("U", "T")
    start = (position - 1) * 3
    codon = cds[start : start + 3]
    if len(codon) != 3:
        raise ValueError(f"CDS is too short for protein position {position}")
    actual_aa = CODON_TABLE.get(codon)
    if actual_aa != ref_aa:
        raise ValueError(
            f"CDS codon {codon} encodes {actual_aa}, not claimed reference "
            f"residue {ref_aa} at position {position}"
        )
    target = _closest_codon(codon, alt_aa)
    diffs = [i for i, (a, b) in enumerate(zip(codon, target, strict=True)) if a != b]
    if len(diffs) == 1:
        idx = diffs[0]
        cds_pos = start + idx + 1
        return f"c.{cds_pos}{codon[idx]}>{target[idx]}"
    cds_start = start + 1
    cds_end = start + len(codon)
    return f"c.{cds_start}_{cds_end}delins{target}"


def lookup_alphamissense(
    validation: MutationValidationResult,
    *,
    transcript_resolver: TranscriptResolver | None = None,
    vep_client: VepClient | None = None,
) -> AlphaMissenseResult:
    if transcript_resolver is None or vep_client is None:
        from secondlook.ensembl import EnsemblTranscriptResolver, EnsemblVepClient

        transcript_resolver = transcript_resolver or EnsemblTranscriptResolver()
        vep_client = vep_client or EnsemblVepClient()

    if validation.status != "valid" or validation.gene is None or validation.position is None:
        return _unavailable(transcript_id=None, hgvs_c=None)

    try:
        transcript_id = transcript_resolver.resolve_mane_select(validation.gene)
    except EnsemblError:
        return _unavailable(transcript_id=None, hgvs_c=None)

    hgvs_c: str | None
    try:
        cds = transcript_resolver.fetch_cds(transcript_id)
        hgvs_c = protein_sub_to_hgvs_c(
            cds,
            position=validation.position,
            ref_aa=validation.reference_residue_expected or "",
            alt_aa=_alt_residue(validation),
        )
        vep_hgvs = hgvs_c
    except (ValueError, EnsemblError):
        hgvs_c = None
        vep_hgvs = validation.hgvs_normalized or ""

    try:
        payload = vep_client.lookup_hgvs(transcript_id, vep_hgvs)
    except EnsemblError:
        return _unavailable(transcript_id=transcript_id, hgvs_c=hgvs_c)

    extracted = extract_alphamissense(payload, transcript_id)
    if extracted is None:
        return _unavailable(transcript_id=transcript_id, hgvs_c=hgvs_c)

    score = extracted["am_pathogenicity"]
    return AlphaMissenseResult(
        status="scored",
        am_pathogenicity=score,
        am_class=classify_alphamissense(score),
        ensembl_am_class=extracted.get("am_class"),
        transcript_id=extracted.get("transcript_id") or transcript_id,
        hgvs_c=hgvs_c,
        note=None,
    )


def _alt_residue(validation: MutationValidationResult) -> str:
    if validation.mutant_sequence is None or validation.position is None:
        raise ValueError("validated mutation is missing mutant sequence or position")
    return validation.mutant_sequence[validation.position - 1]


def _closest_codon(from_codon: str, alt_aa: str) -> str:
    candidates = [codon for codon, aa in CODON_TABLE.items() if aa == alt_aa]
    if not candidates:
        raise ValueError(f"No codon encodes amino acid {alt_aa}")
    return min(candidates, key=lambda codon: _hamming(from_codon, codon))


def _hamming(left: str, right: str) -> int:
    return sum(a != b for a, b in zip(left, right, strict=True))


def _unavailable(*, transcript_id: str | None, hgvs_c: str | None) -> AlphaMissenseResult:
    return AlphaMissenseResult(
        status="unavailable",
        am_pathogenicity=None,
        am_class=None,
        ensembl_am_class=None,
        transcript_id=transcript_id,
        hgvs_c=hgvs_c,
        note=NO_SCORE_NOTE,
    )


def _unversioned(transcript_id: str) -> str:
    return transcript_id.split(".", 1)[0]
