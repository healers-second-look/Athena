"""Case Memory Store -- the event-sourced record of one patient's case.

Postgres holds *the case*; FalkorDB holds *the world* (Tier 1's evidence
graph). They join at exactly one place: `Finding.evidence_ref`. See
`IMPLEMENTATION_PLAN.md` SS2 for the full schema and rationale, and
`POLICY.md` SS5 for what may never be stored here (no PHI: no name, no DOB,
no MRN).
"""
