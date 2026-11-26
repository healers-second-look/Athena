"""Material for the study's chat arm (issue #136, protocol section 3).

Arm C is the shipped chat interface pointed at a study case. To keep content
matched across arms, the chat is given exactly what the other arms show: the
case's findings become its "retrieved sources" (numbered [1], [2], ... so the
issue-#124 citation backstop applies unchanged) and its events become context
lines. The reported changeset is NOT given to the chat -- asking "what
changed?" is answered from the events, as a chat user would experience it.

Limitation, stated rather than hidden: `chat.engine.run_turn` is stateless
across turns (each message is answered without the earlier conversation), which
is how the shipped chat behaves today. Arm C therefore reflects the shipped
chat, including that limitation.
"""

from __future__ import annotations

from secondlook.study.cases import StudyCase


def chat_sources(case: StudyCase) -> list[dict]:
    """The case's findings, shaped like `chat.knowledge` retrieval results."""
    sources = []
    for index, finding in enumerate(case.system_output.findings, start=1):
        citation = finding.citation
        sources.append(
            {
                "id": f"study:{finding.id}",
                "citation_index": index,
                "title": finding.claim,
                "summary": finding.claim,
                "evidence_level": finding.evidence_level or "N/A",
                "pmid": citation.id if citation else "N/A",
                "citation_url": citation.url if citation else "",
                "finding_id": finding.id,
            }
        )
    return sources


def chat_context_lines(case: StudyCase) -> list[str]:
    header = f"Case: {case.cancer_type}"
    if case.age_years is not None:
        header += f", age {case.age_years}"
    if case.stage:
        header += f", stage {case.stage}"
    events = sorted(case.baseline_events + case.update_events, key=lambda e: e.occurred_on)
    return [header] + [f"{e.occurred_on}: {e.summary}" for e in events]


def latest_gene_symbol(case: StudyCase) -> str | None:
    """Gene symbol from the latest case event whose payload includes ``gene``."""
    events = sorted(case.baseline_events + case.update_events, key=lambda e: e.occurred_on)
    for event in reversed(events):
        raw = event.payload.get("gene")
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def gene_context_id(case: StudyCase) -> str | None:
    symbol = latest_gene_symbol(case)
    return f"gene:{symbol}" if symbol else None


def briefing_text(case: StudyCase, *, show_supersessions: bool = False) -> str:
    """The first assistant message: the same findings the other arms list.

    With ``show_supersessions`` (the athena_full arm, whose review tab shows
    Athena's change report), findings the system reports as superseded are
    listed separately with the system's note instead of as current findings.
    Only the system's reported supersessions are used, never ground truth.
    """
    superseded = (
        {s.finding_id: s for s in case.system_output.reported_supersessions}
        if show_supersessions
        else {}
    )
    numbered = list(enumerate(case.system_output.findings, start=1))
    current = [(i, f) for i, f in numbered if f.id not in superseded]
    lines = [f"## {case.label}", "", "I reviewed this case. My current findings:", ""]
    # Plain lines, not "- " bullets: the chat UI renders a bulleted line with its
    # own bullet, so a leading "- " would show up doubled.
    lines += [f"Finding {index}: {finding.claim} [{index}]" for index, finding in current]
    if superseded:
        lines += ["", "No longer current (superseded since the last review):", ""]
        lines += [
            f"Finding {index} (superseded): {finding.claim} [{index}] -- "
            f"{superseded[finding.id].note}"
            for index, finding in numbered
            if finding.id in superseded
        ]
    lines += ["", "Ask me anything about the case."]
    return "\n".join(lines)
