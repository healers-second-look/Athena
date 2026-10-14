// Design law 4 from #14's Part III comment: "Absence must be visible. Empty
// states say *why*. Silent blank panels are a defect, not neutral."
//
// The reason is REQUIRED and this throws without one. That is deliberate and
// it is the same move as DocumentedCard refusing to render without a
// citation: a rule that is merely documented gets skipped by someone in a
// hurry, and the skip is invisible -- a blank panel looks like a working
// panel with nothing in it. Making an unexplained empty state impossible to
// render is the only version of this rule that survives a deadline.
//
// "No trials matched -- 0 candidates passed the gene/disease filter" and
// "trial lookup unavailable" are different sentences because they are
// different facts. This component is for the first. Use DegradeNotice for
// the second: a lookup that failed is not an absence of results, and
// rendering it as one tells the reader we looked and found nothing.
export default function EmptyState({ reason }) {
  if (!reason || !String(reason).trim()) {
    throw new Error(
      'EmptyState requires a reason -- an unexplained empty panel is a defect, not a neutral state',
    )
  }
  return <p className="empty-state">{reason}</p>
}
