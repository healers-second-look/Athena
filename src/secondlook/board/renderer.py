"""Board Record Renderer.

Subsystem AC (Issue #84, P1).

The transparency surface of the multidisciplinary tumor board:
1. Findings organized by specialist lane.
2. Challenges rendered inline directly under target findings.
3. Disagreements preserved side-by-side and labeled.
4. Per-lane coverage and degrade status clearly visible.
5. Every citation is clickable / linked.
6. Computed signals carry the fixed §10 disclaimer verbatim.
7. HARD RULE: Refuses any attempt to hide or filter out the disagreement ledger.
   There is no "summary view" that suppresses disagreements.
"""

from __future__ import annotations

import html

from secondlook.board.fabric import EvidenceClass
from secondlook.board.orchestrator import BoardRecord
from secondlook.pipeline import DISCLAIMER as COMPUTED_SIGNAL_DISCLAIMER


class DisagreementLedgerHiddenError(ValueError):
    """Raised when attempting to render a board record while hiding disagreements."""


def render_board_record(
    record: BoardRecord,
    *,
    format: str = "text",
    hide_disagreements: bool = False,
) -> str:
    """Renders a BoardRecord into text/markdown or HTML format.

    Enforces that disagreements are never suppressed.
    """
    if hide_disagreements:
        raise DisagreementLedgerHiddenError(
            "Hiding or suppressing the disagreement ledger is strictly forbidden. "
            "Disagreement is the primary safety product of the board."
        )

    if format == "html":
        return _render_html(record)
    elif format in ("text", "markdown"):
        return _render_text(record)
    else:
        raise ValueError(f"Unsupported format '{format}'. Use 'text', 'markdown', or 'html'")


def _render_text(record: BoardRecord) -> str:
    lines: list[str] = []
    lines.append(f"# Athena Tumor Board Record — Session {record.session_id}")
    lines.append(f"Case ID: {record.case_id} | Timestamp: {record.timestamp.isoformat()}")
    lines.append(f"Quorum Status: {'VERIFIED' if record.quorum_verified else 'DEGRADED'}")
    lines.append("")

    # Lane Coverage and Degraded Status Summary
    lines.append("## Lane Coverage & Health Status")
    for role_id, cov in sorted(record.lane_coverages.items()):
        status = "DEGRADED" if cov.is_degraded else "HEALTHY"
        lines.append(
            f"- [{role_id}] {status}: nodes={cov.node_count}, "
            f"citation_density={cov.citation_density:.2f}, "
            f"anchor_density={cov.anchor_density:.2f}, "
            f"contradictions={cov.contradiction_count}"
        )
    lines.append("")

    # Union of Missing Data
    lines.append("## Missing Data Audit")
    if record.missing_data_union:
        for item in record.missing_data_union:
            lines.append(f"- [MISSING] {item}")
    else:
        lines.append("- None reported across participating seats.")
    lines.append("")

    # Abstention Audit
    lines.append("## Abstentions by Seat")
    has_abstentions = False
    for role_id, abst_list in sorted(record.abstention_audit.items()):
        if abst_list:
            has_abstentions = True
            for a in abst_list:
                lines.append(f"- [{role_id}] {a}")
    if not has_abstentions:
        lines.append("- All participating seats contributed active claims.")
    lines.append("")

    # Findings by Lane with Inline Challenges
    lines.append("## Findings by Specialist Lane")
    for role_id in record.roles:
        findings = record.get_findings_for_role(role_id)
        if not findings:
            continue

        lines.append(f"### Lane: {role_id.upper()}")
        for f in findings:
            evidence_badge = f.evidence_class.value.upper()
            lines.append(f"#### [{evidence_badge}] Finding {f.finding_id}: {f.claim_kind.value}")
            lines.append(f"Statement: {f.statement}")

            # Identity Anchors
            if f.anchors:
                anchor_strs = [a.canonical_key for a in f.anchors]
                lines.append(f"Identity Anchors: {', '.join(anchor_strs)}")

            # Citations
            if f.citations:
                cite_strs = []
                for i, c in enumerate(f.citations):
                    url = f.citation_urls[i] if i < len(f.citation_urls) else None
                    if url:
                        cite_strs.append(f"[{c}]({url})")
                    else:
                        cite_strs.append(f"[{c}]")
                lines.append(f"Citations: {', '.join(cite_strs)}")

            # Caveats
            if f.caveats:
                lines.append(f"Caveats: {'; '.join(f.caveats)}")

            # Computed Signal Disclaimer
            if f.evidence_class == EvidenceClass.COMPUTED:
                lines.append(f"> [!CAUTION] {COMPUTED_SIGNAL_DISCLAIMER}")

            # Inline Challenges from other roles
            challenges = record.get_challenges_for_finding(f.finding_id)
            if challenges:
                lines.append("  **Challenges on this Finding:**")
                for ch in challenges:
                    c_type = ch.challenge_type.value.upper()
                    lines.append(f"  - [{c_type}] from {ch.challenger_role}: {ch.rationale}")
                    cite_url_str = f" ({ch.citation_url})" if ch.citation_url else ""
                    st = ch.status.value.upper()
                    lines.append(f"    Citation: {ch.citation}{cite_url_str} | Status: {st}")
            lines.append("")

    # Durable Disagreement Ledger Summary
    lines.append("## Disagreement Ledger (Full Verbatim Record)")
    all_challenges = record.disagreement_ledger.all_challenges()
    if all_challenges:
        for ch in all_challenges:
            status_label = ch.status.value.upper()
            lines.append(
                f"- Challenge {ch.challenge_id}: {ch.challenger_role} -> {ch.target_role} "
                f"[{ch.challenge_type.value.upper()}] status={status_label}"
            )
            lines.append(f"  Target Finding: {ch.target_finding_id}")
            lines.append(f"  Rationale: {ch.rationale}")
            lines.append(f"  Challenger Citation: {ch.citation}")
    else:
        lines.append("- No challenges recorded during this session.")
    lines.append("")

    return "\n".join(lines)


def _render_html(record: BoardRecord) -> str:
    quorum_label = "VERIFIED" if record.quorum_verified else "DEGRADED"
    parts: list[str] = [
        f'<div class="athena-board-record" data-session-id="{html.escape(record.session_id)}">',
        f"  <header><h1>Tumor Board Record — Session {html.escape(record.session_id)}</h1>",
        f"  <p><strong>Case:</strong> {html.escape(record.case_id)} | "
        f"<strong>Quorum:</strong> {quorum_label}</p></header>",
        '  <section class="lane-health"><h2>Lane Health & Coverage</h2><ul>',
    ]

    for role_id, cov in sorted(record.lane_coverages.items()):
        status = "degraded" if cov.is_degraded else "healthy"
        parts.append(
            f'    <li class="lane-status-{status}"><strong>{html.escape(role_id)}</strong>: '
            f"{status.upper()} (nodes={cov.node_count}, density={cov.citation_density:.2f}, "
            f"contradictions={cov.contradiction_count})</li>"
        )
    parts.append("  </ul></section>")

    # Missing Data
    parts.append('  <section class="missing-data"><h2>Missing Data Audit</h2><ul>')
    if record.missing_data_union:
        for item in record.missing_data_union:
            parts.append(f'    <li class="missing-item">{html.escape(item)}</li>')
    else:
        parts.append("    <li>None reported</li>")
    parts.append("  </ul></section>")

    # Findings and Inline Challenges
    parts.append('  <section class="findings-by-lane"><h2>Findings by Specialist Lane</h2>')
    for role_id in record.roles:
        findings = record.get_findings_for_role(role_id)
        if not findings:
            continue
        parts.append(f'    <div class="lane-block" data-role="{html.escape(role_id)}">')
        parts.append(f"      <h3>Lane: {html.escape(role_id.upper())}</h3>")

        for f in findings:
            f_class = f.evidence_class.value
            f_id = html.escape(f.finding_id)
            parts.append(f'      <article class="finding finding-{f_class}" id="{f_id}">')
            ev_upper = html.escape(f_class.upper())
            claim_label = html.escape(f.claim_kind.value)
            parts.append(
                f'        <header><span class="badge badge-{f_class}">{ev_upper}</span> '
                f"<strong>{claim_label}</strong></header>"
            )
            parts.append(f'        <p class="statement">{html.escape(f.statement)}</p>')

            if f.citations:
                cite_items: list[str] = []
                for i, c in enumerate(f.citations):
                    url = f.citation_urls[i] if i < len(f.citation_urls) else None
                    if url:
                        link_html = (
                            f'<a href="{html.escape(url)}" target="_blank" '
                            f'rel="noopener noreferrer">{html.escape(c)}</a>'
                        )
                        cite_items.append(link_html)
                    else:
                        cite_items.append(f"<span>{html.escape(c)}</span>")
                parts.append(
                    f"        <div class=\"citations\">Citations: {', '.join(cite_items)}</div>"
                )

            if f.evidence_class == EvidenceClass.COMPUTED:
                disc = html.escape(COMPUTED_SIGNAL_DISCLAIMER)
                parts.append(f'        <div class="computed-disclaimer">{disc}</div>')

            # Inline challenges
            challenges = record.get_challenges_for_finding(f.finding_id)
            if challenges:
                parts.append('        <div class="inline-challenges"><h5>Challenges</h5><ul>')
                for ch in challenges:
                    c_type = ch.challenge_type.value
                    c_badge = html.escape(c_type.upper())
                    ch_role = html.escape(ch.challenger_role)
                    ch_rat = html.escape(ch.rationale)
                    ch_cite = html.escape(ch.citation)
                    parts.append(
                        f'          <li class="challenge challenge-{c_type}">'
                        f'<span class="challenge-type">{c_badge}</span> '
                        f"from <strong>{ch_role}</strong>: {ch_rat} "
                        f'<span class="challenger-cite">[Cite: {ch_cite}]</span></li>'
                    )
                parts.append("        </ul></div>")

            parts.append("      </article>")
        parts.append("    </div>")
    parts.append("  </section>")

    # Disagreement ledger
    parts.append(
        '  <section class="disagreement-ledger"><h2>Disagreement Ledger (Verbatim)</h2><ul>'
    )
    for ch in record.disagreement_ledger.all_challenges():
        c_from = html.escape(ch.challenger_role)
        c_tgt = html.escape(ch.target_role)
        c_fid = html.escape(ch.target_finding_id)
        c_rat = html.escape(ch.rationale)
        c_cite = html.escape(ch.citation)
        c_stat = html.escape(ch.status.value.upper())
        parts.append(
            f'    <li class="ledger-entry status-{ch.status.value}">'
            f"<strong>{c_from}</strong> challenged <strong>{c_tgt}</strong> on finding "
            f"<code>{c_fid}</code>: {c_rat} "
            f'<span class="cite">({c_cite})</span> [Status: {c_stat}]</li>'
        )
    parts.append("  </ul></section>")
    parts.append("</div>")

    return "\n".join(parts)
