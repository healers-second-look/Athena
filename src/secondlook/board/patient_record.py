"""Patient-Readable Board Record.

Subsystem AF (Issue #87, P2).

The seat the patient occupies in their own care:
1. Derived strictly from the clinical BoardRecord; never separately generated.
   Two generators means two truths.
2. Plain-language rendering without softening findings, omitting caveats,
   or suppressing disagreements.
3. Explicitly surfaces two mandatory patient sections:
   - What additional data would change this answer (missing data and tests).
   - What access routes exist and what each requires (trials and logistics).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from secondlook.board.orchestrator import BoardRecord


@dataclass(frozen=True)
class PatientReadableRecord:
    """Plain-language view of a multidisciplinary tumor board record."""

    session_id: str
    case_id: str
    summary_plain_text: str
    what_would_change_this_answer: tuple[str, ...]
    access_pathways_and_next_steps: tuple[str, ...]
    open_disagreements: tuple[dict[str, str], ...]
    is_complete: bool


def generate_patient_readable_record(record: BoardRecord) -> PatientReadableRecord:
    """Translates a BoardRecord into a patient-accessible summary.

    Strict invariant: Reads only from the existing BoardRecord. Never calls
    a second generator or invents content outside the board's findings.
    """
    # 1. Missing data: What would change this answer?
    what_would_change: list[str] = []
    for item in record.missing_data_union:
        what_would_change.append(f"Additional test required: {item}")
    for role, abst_list in record.abstention_audit.items():
        for abst in abst_list:
            what_would_change.append(f"{role.replace('_', ' ').title()} noted: {abst}")

    if not what_would_change:
        what_would_change.append("No additional baseline diagnostic tests currently pending.")

    # 2. Access routes and next steps
    access_routes: list[str] = []
    # Extract findings from trials_access_officer or patient_navigator if present
    for role_id in ("trials_access_officer", "patient_navigator"):
        for f in record.get_findings_for_role(role_id):
            access_routes.append(f"{f.statement} (Source: {role_id})")

    if not access_routes:
        access_routes.append(
            "Standard clinical treatment pathway. Discuss clinical trial matching and "
            "financial navigation with your care team."
        )

    # 3. Open disagreements (unresolved challenges shown honestly to the patient)
    disagreements: list[dict[str, str]] = []
    for ch in record.disagreement_ledger.all_challenges():
        challenger_title = ch.challenger_role.replace("_", " ").title()
        target_title = ch.target_role.replace("_", " ").title()
        disagreements.append(
            {
                "challenger": challenger_title,
                "target": target_title,
                "question_raised": ch.rationale,
                "type": ch.challenge_type.value,
            }
        )

    # 4. Summary text
    role_count = len(record.roles)
    finding_count = len(record.all_findings)
    summary_lines: list[str] = [
        f"Your case was reviewed by the tumor board ({role_count} specialist seats).",
        f"A total of {finding_count} clinical findings were established across specialties.",
    ]
    if disagreements:
        summary_lines.append(
            f"Your team had {len(disagreements)} active discussion points regarding treatment "
            "trade-offs, which are detailed below."
        )

    return PatientReadableRecord(
        session_id=record.session_id,
        case_id=record.case_id,
        summary_plain_text="\n".join(summary_lines),
        what_would_change_this_answer=tuple(what_would_change),
        access_pathways_and_next_steps=tuple(access_routes),
        open_disagreements=tuple(disagreements),
        is_complete=record.quorum_verified,
    )


def render_patient_record_html(patient_rec: PatientReadableRecord) -> str:
    """Renders the patient-readable record into clean semantic HTML."""
    escaped_summary = html.escape(patient_rec.summary_plain_text)
    parts: list[str] = [
        f'<article class="athena-patient-record" data-case="{html.escape(patient_rec.case_id)}">',
        "  <header><h1>Your Tumor Board Review Summary</h1></header>",
        f'  <section class="patient-overview"><p>{escaped_summary}</p></section>',
        '  <section class="what-changes">',
        "    <h2>What Additional Data Would Change This Answer?</h2>",
        "    <ul>",
    ]

    for item in patient_rec.what_would_change_this_answer:
        parts.append(f"      <li>{html.escape(item)}</li>")
    parts.append("    </ul>")
    parts.append("  </section>")

    parts.append('  <section class="access-routes">')
    parts.append("    <h2>Access Routes & Next Steps</h2>")
    parts.append("    <ul>")
    for route in patient_rec.access_pathways_and_next_steps:
        parts.append(f"      <li>{html.escape(route)}</li>")
    parts.append("    </ul>")
    parts.append("  </section>")

    parts.append('  <section class="patient-disagreements">')
    parts.append("    <h2>Points Discussed by Your Specialists</h2>")
    if patient_rec.open_disagreements:
        parts.append("    <ul>")
        for d in patient_rec.open_disagreements:
            ch_role = html.escape(d["challenger"])
            tgt_role = html.escape(d["target"])
            q_raised = html.escape(d["question_raised"])
            parts.append(
                f"      <li><strong>{ch_role}</strong> raised a consideration with "
                f"<strong>{tgt_role}</strong>: {q_raised}</li>"
            )
        parts.append("    </ul>")
    else:
        parts.append("    <p>Your team was in full agreement on all evaluated findings.</p>")
    parts.append("  </section>")
    parts.append("</article>")

    return "\n".join(parts)
