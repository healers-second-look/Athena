import { derivePlainLanguage } from '../i18n.js'

export default function PlainLanguageBox({ finding, lang = 'en' }) {
  if (!finding) return null
  const pl = derivePlainLanguage(finding, lang)

  return (
    <div className="plain-box" data-testid="plain-language-box">
      <div className="plain-box-title">{pl.title}</div>
      <p className="plain-warrant" style={{ margin: '.2rem 0' }}>{pl.warrant}</p>
      <p className="small muted" style={{ margin: '.3rem 0' }}>{pl.claim}</p>
      {pl.caveats.length > 0 ? (
        <div className="plain-caveats" style={{ marginTop: '.4rem' }}>
          <span className="small muted">{pl.caveatHeading}</span>
          <ul className="caveats" style={{ marginTop: '.2rem' }}>
            {pl.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
