import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import EvidenceCard from '../components/evidence/index.jsx'
import PlainLanguageBox from '../components/PlainLanguageBox.jsx'
import { t } from '../i18n.js'
import useAsync from '../api/useAsync.js'
import { getFinding } from '../api/client.js'
import { Failure } from './CaseDashboard.jsx'

// §9 — Finding Detail. Claim, evidence class badge, full provenance chain
// (clickable through to PubMed/CIViC), review buttons.
//
// This screen also has a server-rendered twin at the same path served without
// JavaScript (secondlook/web/render.py). Both exist deliberately: this one is
// reachable instantly from the queue once the bundle is warm, and the other
// costs one request and ~3.7 KB gzipped on a cold 3G connection.
export default function FindingDetail() {
  const { id } = useParams()
  const [lang, setLang] = useState('en')
  const [plain, setPlain] = useState(false)
  const finding = useAsync(() => getFinding(id), [id])
  const paired = useAsync(
    () => (finding.data?.paired_with ? getFinding(finding.data.paired_with) : Promise.resolve(null)),
    [finding.data?.paired_with],
  )

  if (finding.loading) return <p className="muted">Loading finding…</p>
  if (finding.error) return <Failure what="finding" error={finding.error} />

  const f = finding.data
  const superseded = f.status === 'superseded'

  return (
    <>
      <div className="lang-nav">
        <button
          type="button"
          className={`lang-btn ${lang === 'en' ? 'active' : ''}`}
          onClick={() => setLang('en')}
        >
          English
        </button>
        <button
          type="button"
          className={`lang-btn ${lang === 'hi' ? 'active' : ''}`}
          onClick={() => setLang('hi')}
        >
          हिन्दी
        </button>
        <button
          type="button"
          className={`lang-btn ${plain ? 'active' : ''}`}
          onClick={() => setPlain(!plain)}
          aria-pressed={plain}
        >
          {t('plain_language.toggle_button', lang)}
        </button>
      </div>

      <p className="small muted">
        <Link to={`/cases/${f.case_id}`}>← {t('labels.case_dashboard', lang)}</Link>
      </p>
      <h1>{f.label || 'Finding'}</h1>
      <p className="small muted">In answer to: {f.question_text}</p>

      {superseded ? (
        <section className="banner" role="alert">
          <div className="banner-head">⊘ {t('status.superseded', lang)}</div>
          <div className="supersession-why">{f.superseded_note}</div>
          <div className="supersession-trigger">
            → {f.superseded_event_label || f.superseded_by}
          </div>
          {/* Struck, never deleted. The historical record is the point
              (IMPLEMENTATION_PLAN.md §4.2). */}
          <div className="superseded-claim" style={{ marginTop: '.5rem' }}>{f.claim}</div>
        </section>
      ) : null}

      <EvidenceCard finding={f} />
      {plain ? <PlainLanguageBox finding={f} lang={lang} /> : null}

      {paired.data ? (
        <>
          <h2>The other half of this trial</h2>
          <p className="small muted">
            As of issue #46 a matched trial produces two signals: the registry’s
            record that it exists, and our own computed verdict on whether this
            patient fits it. They have different warrants and are shown separately —
            reconciling them is a clinician’s call, not the generator’s.
          </p>
          <EvidenceCard finding={paired.data} />
          {plain ? <PlainLanguageBox finding={paired.data} lang={lang} /> : null}
        </>
      ) : null}

      <h2>{t('labels.provenance', lang)}</h2>
      <Provenance entries={f.provenance} lang={lang} />

      <h2>{t('labels.clinician_review', lang)}</h2>
      <Decisions entries={f.decisions} lang={lang} />
      <ReviewForm findingId={f.id} lang={lang} />
    </>
  )
}

function Provenance({ entries = [], lang = 'en' }) {
  if (!entries.length) {
    return <p className="muted small">{t('labels.no_provenance', lang)}</p>
  }
  // Every step renders, including steps with no URL. An unlinkable step is
  // still part of the chain, and dropping it makes the chain look shorter
  // — and therefore stronger — than it is.
  return (
    <ol className="provenance">
      {entries.map((e, i) => (
        <li key={i}>
          <div className="step">{e.step}</div>
          <div className="detail">
            {e.detail}
            {e.url ? (
              <>{' · '}<a href={e.url} rel="noreferrer noopener" target="_blank">{t('labels.open_source', lang)}</a></>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  )
}

function Decisions({ entries = [], lang = 'en' }) {
  if (!entries.length) return <p className="muted small">{t('labels.no_review', lang)}</p>
  return (
    <ul className="caveats">
      {entries.map((d, i) => (
        <li key={i}>
          <strong>{d.action}</strong> — {d.reason}
          <div className="small muted">{d.decided_by}, {d.decided_at}</div>
        </li>
      ))}
    </ul>
  )
}

function ReviewForm({ findingId, lang = 'en' }) {
  const [reason, setReason] = useState('')
  const [action, setAction] = useState(null)

  // A reason is required with EVERY decision, including "investigating"
  // (case/models.py: Decision.reason is NOT NULL, "required, even for
  // investigating"). The button is disabled rather than the reason being
  // defaulted to an empty string, so the constraint is visible in the UI
  // rather than discovered as a 500 from the API.
  const submit = (event) => {
    event.preventDefault()
    if (!action || !reason.trim()) return
    // Subsystem L owns POST /api/findings/{id}/decision. Until it exists the
    // form does not pretend to have saved anything.
    window.alert(
      `Not yet wired: POST /api/findings/${findingId}/decision\n\n` +
      `action=${action}\nreason=${reason}\n\n` +
      'Subsystem L (issue #13) owns this endpoint.',
    )
  }

  return (
    <form className="actions" onSubmit={submit} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
      <label className="small muted" htmlFor="reason">{t('labels.reason_label', lang)}</label>
      <textarea
        id="reason"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        style={{ font: 'inherit', padding: '.4rem', border: '1px solid var(--rule)' }}
      />
      <div className="actions">
        {['investigating', 'deferred', 'rejected'].map((a) => (
          <button
            key={a}
            type="submit"
            onClick={() => setAction(a)}
            disabled={!reason.trim()}
            title={reason.trim() ? undefined : t('labels.reason_required', lang)}
          >
            {t(`actions.${a}`, lang)}
          </button>
        ))}
      </div>
    </form>
  )
}
