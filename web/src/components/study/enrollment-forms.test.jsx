import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import UsualCareView from './UsualCareView.jsx'
import { EvidenceLookupForm } from './TaskForms.jsx'
import SusForm, { SUS_ITEMS, susItems } from './SusForm.jsx'

const baseView = {
  case_id: 'c1',
  label: 'Case',
  cancer_type: 'Breast',
  age_years: 50,
  stage: 'IV',
  baseline_events: [],
  update_events: [],
  findings: [
    {
      id: 'f1',
      claim: 'Claim',
      evidence_class: 'documented',
      citation: { id: 'c1', url: 'https://example.org/c1', name: 'Ref' },
    },
  ],
  reported_changes: [{ kind: 'x', summary: 'change' }],
  reported_supersessions: [],
  questions: [{ id: 'q1', text: 'Question?' }],
}

describe('UsualCareView', () => {
  it('renders no diff content and logs external_source_logged', () => {
    const onEvent = vi.fn()
    const { container } = render(
      <UsualCareView view={baseView} onFindingOpened={() => {}} onCitationOpened={() => {}} onEvent={onEvent} />,
    )
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(/open questions/i)).toBeNull()
    expect(container.querySelector('.study-finding--superseded')).toBeNull()

    fireEvent.change(screen.getByLabelText(/^URL/i), { target: { value: 'https://pubmed.ncbi.nlm.nih.gov/1' } })
    // No default type: a doctor who never touches the menu must not log a PubMed link as a guideline.
    expect(screen.getByRole('button', { name: /log source/i })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /log source/i }))
    expect(onEvent).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText(/^Type/i), { target: { value: 'PubMed' } })
    fireEvent.click(screen.getByRole('button', { name: /log source/i }))
    expect(onEvent).toHaveBeenCalledWith('external_source_logged', {
      url: 'https://pubmed.ncbi.nlm.nih.gov/1',
      type: 'PubMed',
    })
  })
})

describe('TaskForms', () => {
  it('emits task_answer_submitted with confidence', () => {
    const onEvent = vi.fn()
    const onSubmit = vi.fn()
    render(
      <EvidenceLookupForm question="What is the guideline?" onEvent={onEvent} onSubmit={onSubmit} />,
    )
    fireEvent.change(screen.getByLabelText(/your answer/i), { target: { value: 'Answer text' } })
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '80' } })
    fireEvent.pointerUp(slider)
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(onEvent).toHaveBeenCalledWith(
      'task_answer_submitted',
      expect.objectContaining({ task: 'evidence_lookup', confidence: 80 }),
    )
  })
})

describe('SusForm', () => {
  it('renders 10 items and emits sus_submitted', () => {
    const onEvent = vi.fn()
    const { container } = render(<SusForm armLabel="usual_care" onEvent={onEvent} onSubmit={() => {}} />)
    expect(SUS_ITEMS).toHaveLength(10)
    const submit = screen.getByRole('button', { name: /continue/i })
    expect(submit).toBeDisabled()
    container.querySelectorAll('.study-sus-item').forEach((item) => {
      fireEvent.click(item.querySelectorAll('input[type="radio"]')[2])
    })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    expect(onEvent).toHaveBeenCalledWith('sus_submitted', expect.objectContaining({ arm: 'usual_care' }))
    // The saved item text is the wording the doctor actually saw.
    expect(onEvent.mock.calls[0][1].responses[0].text).toBe(
      'I think that I would like to use my usual tools frequently.',
    )
  })

  it('names what is being rated instead of "the system"', () => {
    for (const arm of ['usual_care', 'athena_full']) {
      const items = susItems(arm)
      expect(items).toHaveLength(10)
      for (const text of items) expect(text).not.toMatch(/system|\{/)
    }
    expect(susItems('usual_care').every((t) => t.includes('my usual tools'))).toBe(true)
    expect(susItems('athena_full').every((t) => t.includes('Athena'))).toBe(true)
  })
})