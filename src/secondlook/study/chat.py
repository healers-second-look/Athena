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


def briefing_text(case: StudyCase) -> str:
    """The first assistant message: the same findings the other arms list."""
    lines = [f"## {case.label}", "", "I reviewed this case. My current findings:"]
    lines += [
        f"- {finding.claim} [{index}]"
        for index, finding in enumerate(case.system_output.findings, start=1)
    ]
    lines += ["", "Ask me anything about the case."]
    return "\n".join(lines)
