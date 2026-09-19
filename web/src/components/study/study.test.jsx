import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AssessmentForm from './AssessmentForm.jsx'
import DashboardView from './DashboardView.jsx'
import DiffFirstView from './DiffFirstView.jsx'
import RecallForm from './RecallForm.jsx'
import StudyFindings from './StudyFindings.jsx'
import TlxForm, { TLX_ITEMS } from './TlxForm.jsx'

// Mirrors the shape of GET /api/study/cases/{id}?arm=... (study/views.py).
const findings = [
  {
    id: 'f1',
    claim: 'Continue aromatase-inhibitor therapy.',
    evidence_class: 'documented',
    evidence_level: 'B',
    citation: { id: 'SYN-1', url: 'https://example.org/synthetic/f1', name: 'Synthetic placeholder' },
  },
  {
    id: 'f2',
    claim: 'A CDK4/6 inhibitor plus endocrine therapy is standard first-line.',
    evidence_class: 'documented',
    evidence_level: 'A',
    citation: { id: 'SYN-2', url: 'https://example.org/synthetic/f2', name: 'Synthetic placeholder' },
  },
]

const baseView = {
  case_id: 'c1',
  label: 'Case one',
  cancer_type: 'HR+/HER2- breast cancer',
  age_years: 58,
  stage: 'IV',
  baseline_events: [
    { id: 'b1', occurred_on: '2023-04-02', event_type: 'TREATMENT_LINE', summary: 'Adjuvant letrozole started' },
  ],
  update_events: [
    { id: 'u1', occurred_on: '2026-01-15', event_type: 'ALTERATION_OBSERVED', summary: 'ESR1 Y537S detected' },
  ],
  findings,
  decision_prompt: 'Next step?',
  decision_options: [
    { id: 'a', text: 'Continue unchanged' },
    { id: 'b', text: 'Change endocrine partner' },
  ],
  reported_changes: [],
  reported_supersessions: [],
  questions: [],
}

const diffView = {
  ...baseView,
  arm: 'diff_first',
  reported_changes: [{ kind: 'new_alteration', summary: 'ESR1 Y537S newly observed', triggering_event: 'u1' }],
  reported_supersessions: [
    { finding_id: 'f1', broken_assumption: 'no known ESR1 alteration', triggering_event: 'u1', note: 'This finding assumed no ESR1 alteration.' },
  ],
  questions: [{ id: 'q1', text: 'What endocrine options remain?' }],
}

describe('arms: only diff-first is given the diff', () => {
  it('diff-first shows the change banner, a struck finding and the worklist', () => {
    const { container } = render(<DiffFirstView view={diffView} />)
    expect(screen.getByRole('alert')).toHaveTextContent('1 change')
    expect(screen.getByText('What endocrine options remain?')).toBeInTheDocument()
    expect(container.querySelector('.study-finding--superseded')).not.toBeNull()
    expect(container.querySelectorAll('.study-finding--superseded')).toHaveLength(1)
  })

  it('dashboard shows none of that, even when the same findings are supplied', () => {
    const { container } = render(<DashboardView view={{ ...baseView, arm: 'dashboard' }} />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(/open questions/i)).toBeNull()
    expect(container.querySelector('.study-finding--superseded')).toBeNull()
    expect(container.querySelector('.superseded-claim')).toBeNull()
    expect(container.querySelector('li.is-new')).toBeNull() // no "new event" highlight
  })

  it('both arms list the same findings with the same citations (matched content)', () => {
    const a = render(<DiffFirstView view={diffView} />)
    const aClaims = [...a.container.querySelectorAll('.study-finding .claim')].map((n) => n.textContent)
    a.unmount()
    const b = render(<DashboardView view={{ ...baseView, arm: 'dashboard' }} />)
    const bClaims = [...b.container.querySelectorAll('.study-finding .claim')].map((n) => n.textContent)
    expect(aClaims).toEqual(bClaims)
    expect(b.container.querySelectorAll('.study-finding a')).toHaveLength(2) // inline citation on each
  })

  it('a struck finding still uses a literal strikethrough rule', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const css = readFileSync(resolve(process.cwd(), 'src/styles/study.css'), 'utf8')
    expect(css).toMatch(/\.study-finding--superseded \.claim\s*\{[^}]*text-decoration:\s*line-through/)
  })
})

describe('findings interaction logging', () => {
  it('reports a citation click separately from opening a finding', () => {
    const onFindingOpened = vi.fn()
    const onCitationOpened = vi.fn()
    const { container } = render(
      <StudyFindings findings={findings} onFindingOpened={onFindingOpened} onCitationOpened={onCitationOpened} />,
    )
    fireEvent.click(container.querySelector('[data-finding-id="f2"] a'))
    expect(onCitationOpened).toHaveBeenCalledWith('f2', 'https://example.org/synthetic/f2')
    expect(onFindingOpened).not.toHaveBeenCalled()

    fireEvent.click(container.querySelector('[data-finding-id="f1"] .claim'))
    expect(onFindingOpened).toHaveBeenCalledWith('f1')
  })
})

describe('assessment form (same in every arm)', () => {
  const setup = () => {
    const onEvent = vi.fn()
    const onSubmit = vi.fn()
    const utils = render(
      <AssessmentForm
        findings={findings}
        options={baseView.decision_options}
        prompt="Next step?"
        onEvent={onEvent}
        onSubmit={onSubmit}
      />,
    )
    return { onEvent, onSubmit, ...utils }
  }

  it('never shows a superseded mark, so the form cannot carry the treatment', () => {
    const { container } = setup()
    expect(container.textContent).not.toMatch(/superseded/i)
    expect(container.querySelector('.superseded-claim')).toBeNull()
  })

  it('cannot be submitted until every finding and the decision are answered', () => {
    const { onSubmit } = setup()
    const submit = screen.getByRole('button', { name: /submit assessment/i })
    expect(submit).toBeDisabled()
    fireEvent.click(submit)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('an untouched slider does not count as an answer', () => {
    setup()
    // Answer flags and the decision but leave confidence untouched.
    screen.getAllByLabelText('Valid and supported').forEach((radio) => fireEvent.click(radio))
    fireEvent.click(screen.getByLabelText('Continue unchanged'))
    expect(screen.getByRole('button', { name: /submit assessment/i })).toBeDisabled()
  })

  it('submits a full snapshot and logs flag changes', () => {
    const { onEvent, onSubmit } = setup()
    const validRadios = screen.getAllByLabelText('Valid and supported')
    const flagRadios = screen.getAllByLabelText(/Flag: no longer valid/)
    fireEvent.click(flagRadios[0]) // flag finding 1
    fireEvent.click(validRadios[1]) // finding 2 is fine
    const sliders = screen.getAllByLabelText(/How confident/)
    fireEvent.change(sliders[0], { target: { value: '20' } })
    fireEvent.change(sliders[1], { target: { value: '90' } })
    fireEvent.click(screen.getByLabelText('Change endocrine partner'))
    fireEvent.click(screen.getByRole('button', { name: /submit assessment/i }))

    expect(onEvent).toHaveBeenCalledWith('flag_set', { finding_id: 'f1' })
    expect(onSubmit).toHaveBeenCalledWith({
      flags: { f1: true, f2: false },
      confidence: { f1: 20, f2: 90 },
      decision: 'b',
      rationale: '',
    })
  })
})

describe('flag events', () => {
  it('logs flag_cleared only when a flagged finding is un-flagged', () => {
    const onEvent = vi.fn()
    render(
      <AssessmentForm findings={findings} options={baseView.decision_options} prompt="?" onEvent={onEvent} onSubmit={() => {}} />,
    )
    const valid = screen.getAllByLabelText('Valid and supported')
    const flag = screen.getAllByLabelText(/Flag: no longer valid/)
    fireEvent.click(valid[0]) // first answer is "valid": not a clearing
    expect(onEvent).not.toHaveBeenCalled()
    fireEvent.click(flag[0])
    expect(onEvent).toHaveBeenLastCalledWith('flag_set', { finding_id: 'f1' })
    fireEvent.click(valid[0]) // now it really is cleared
    expect(onEvent).toHaveBeenLastCalledWith('flag_cleared', { finding_id: 'f1' })
  })
})

describe('workload and recall forms', () => {
  it('NASA-TLX needs all six subscales', () => {
    const onSubmit = vi.fn()
    render(<TlxForm onSubmit={onSubmit} />)
    expect(TLX_ITEMS).toHaveLength(6)
    const button = screen.getByRole('button', { name: /continue/i })
    expect(button).toBeDisabled()
    TLX_ITEMS.forEach((item) => {
      fireEvent.change(screen.getByLabelText(new RegExp(`^${item.label.split(':')[0]}`)), {
        target: { value: '40' },
      })
    })
    expect(button).toBeEnabled()
    fireEvent.click(button)
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ mental: 40, physical: 40, temporal: 40, performance: 40, effort: 40, frustration: 40 }),
    )
  })

  it('a rating of exactly 50 (the resting position) can be given by releasing the pointer', () => {
    const onSubmit = vi.fn()
    render(<TlxForm onSubmit={onSubmit} />)
    const button = screen.getByRole('button', { name: /continue/i })
    screen.getAllByRole('slider').forEach((slider) => fireEvent.pointerUp(slider)) // no value change
    expect(button).toBeEnabled()
    fireEvent.click(button)
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ mental: 50, frustration: 50 }))
  })

  it('tabbing onto a slider is not an answer', () => {
    render(<TlxForm onSubmit={() => {}} />)
    screen.getAllByRole('slider').forEach((slider) => fireEvent.keyUp(slider, { key: 'Tab' }))
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('recall submits the selected opaque ids (and may submit none)', () => {
    const onSubmit = vi.fn()
    render(
      <RecallForm
        options={[
          { id: '3458485b', text: 'ESR1 Y537S detected' },
          { id: '6299e4d6', text: 'New brain metastasis identified' },
        ]}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.click(screen.getByLabelText('ESR1 Y537S detected'))
    fireEvent.click(screen.getByRole('button', { name: /finish case/i }))
    expect(onSubmit).toHaveBeenCalledWith(['3458485b'])
  })
})
