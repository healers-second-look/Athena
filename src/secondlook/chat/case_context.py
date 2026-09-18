"""Render a folded CaseState as chat CONTEXT lines, never as sources.

Patient facts -- diagnosis, alterations, treatment history, assessments,
clinical questions -- are the doctor's own record, not retrieved evidence.
Issue #107's context-vs-sources split is load-bearing: anything that lands
in `turn.sources` gets a numbered bracket index and inflates
`sources_count`, which makes `citation_overclaim` fire on honest answers.
This module is therefore a pure function over the already-folded state
object. It takes neither a case_id nor a store, matching the DI discipline
in `case/diff.py` and `case/state.py` so the chat engine stays
offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from secondlook.case.state import (
    Alteration,
    BiomarkerValue,
    CaseState,
    DiseaseAssessment,
    TreatmentEntry,
)

_NOT_RECORDED = "not recorded"


class CaseUnavailable(RuntimeError):
    """The case record could not be read.

    Typed on purpose, per `ARCHITECTURE.md` SS8.2: the I/O that can fail
    (Postgres) raises this at its own call site rather than letting a bare
    `Exception` stand in for every failure mode. `chat/knowledge.py`'s
    `GraphUnavailable` is the same pattern for the other store.
    """


@dataclass(frozen=True)
class Diagnosis:
    """The static half of a case -- what lives on the Case row, not the fold.

    Cancer type and histology are P0 in `patient-schema-mvp.md` SS1 and
    essentially never change, so they are not event-sourced and therefore
    never appear in `CaseState`. A chat that cannot say what cancer the
    patient has is not a patient chat, so they are carried alongside.
    """

    cancer_type: str | None = None
    primary_site: str | None = None
    histology: str | None = None
    stage: str | None = None


@dataclass(frozen=True)
class CaseSnapshot:
    """Everything the chat knows about one patient at one instant.

    The static diagnosis plus the folded event state. One type, so that
    adding what the chat may see next (active findings, open questions)
    widens this dataclass instead of re-cutting `run_turn`'s signature.
    """

    state: CaseState
    diagnosis: Diagnosis | None = None


def describe_case(snapshot: CaseSnapshot) -> list[str]:
    """Deterministic fact lines for `snapshot`. Same input, same list, always.

    Headline fields (cancer type/diagnosis, alterations, treatments, latest
    assessment, current clinical question) always appear: populated when
    present, otherwise an explicit "not recorded" line -- a silent omission
    would read as "the patient has none of these", which is a different and
    more dangerous claim. Non-headline sections (biomarkers) are omitted
    entirely when empty.
    """
    state = snapshot.state
    lines = [
        _diagnosis_line(snapshot.diagnosis),
        _alterations_line(state),
        *_treatment_lines(state),
        _assessment_line(state),
        _question_line(state),
    ]
    biomarker_line = _biomarker_line(state)
    if biomarker_line is not None:
        lines.append(biomarker_line)
    return lines


def _diagnosis_line(diagnosis: Diagnosis | None) -> str:
    if diagnosis is None:
        return f"Cancer type / diagnosis: {_NOT_RECORDED}"
    parts = [
        p
        for p in (
            diagnosis.cancer_type,
            diagnosis.histology,
            f"primary site {diagnosis.primary_site}" if diagnosis.primary_site else None,
            f"stage {diagnosis.stage}" if diagnosis.stage else None,
        )
        if p
    ]
    if not parts:
        return f"Cancer type / diagnosis: {_NOT_RECORDED}"
    return "Cancer type / diagnosis: " + ", ".join(parts)


def _alterations_line(state: CaseState) -> str:
    if not state.alterations:
        return f"Known alterations: {_NOT_RECORDED}"
    rendered = "; ".join(_format_alteration(alt) for alt in state.alterations)
    return f"Known alterations: {rendered}"


def _format_alteration(alt: Alteration) -> str:
    extras: list[str] = []
    if alt.variant_type:
        extras.append(alt.variant_type)
    if alt.assay:
        extras.append(f"assay {alt.assay}")
    if alt.tested_on:
        extras.append(f"tested {alt.tested_on}")
    core = f"{alt.gene} {alt.variant}"
    if extras:
        return f"{core} ({'; '.join(extras)})"
    return core


def _treatment_lines(state: CaseState) -> list[str]:
    if not state.treatments:
        return [f"Treatment lines: {_NOT_RECORDED}"]
    lines = ["Treatment lines:"]
    for tx in state.treatments:
        lines.append(f"- {_format_treatment(tx)}")
    return lines


def _format_treatment(tx: TreatmentEntry) -> str:
    line = f"line {tx.line}" if tx.line is not None else "line unknown"
    text = f"{line}: {tx.regimen} {tx.action}"
    if tx.reason:
        text += f" ({tx.reason})"
    return text


def _assessment_line(state: CaseState) -> str:
    if not state.assessments:
        return f"Latest disease assessment: {_NOT_RECORDED}"
    return f"Latest disease assessment: {_format_assessment(state.assessments[-1])}"


def _format_assessment(assessment: DiseaseAssessment) -> str:
    extras: list[str] = []
    if assessment.sites:
        extras.append(f"sites: {', '.join(assessment.sites)}")
    if assessment.assessed_on:
        extras.append(f"assessed {assessment.assessed_on}")
    if extras:
        return f"{assessment.status} ({'; '.join(extras)})"
    return assessment.status


def _question_line(state: CaseState) -> str:
    if not state.clinical_questions:
        return f"Current clinical question: {_NOT_RECORDED}"
    return f"Current clinical question: {state.clinical_questions[-1]}"


def _biomarker_line(state: CaseState) -> str | None:
    if not state.biomarkers:
        return None
    parts = [_format_biomarker(bm) for bm in state.biomarkers.values()]
    return "Biomarkers: " + "; ".join(parts)


def _format_biomarker(bm: BiomarkerValue) -> str:
    chunk = f"{bm.name} {bm.value}"
    if bm.unit:
        chunk += f" {bm.unit}"
    if bm.measured_on:
        chunk += f" (measured {bm.measured_on})"
    return chunk


__all__ = ["CaseSnapshot", "CaseUnavailable", "Diagnosis", "describe_case"]
