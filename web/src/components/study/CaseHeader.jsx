export default function CaseHeader({ view }) {
  return (
    <>
      <h1>{view.label}</h1>
      <p className="small muted">
        {view.cancer_type}
        {view.age_years != null ? ` · age ${view.age_years}` : null}
        {view.stage ? ` · stage ${view.stage}` : null}
      </p>
    </>
  )
}
