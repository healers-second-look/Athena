import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import StudyCase from './StudyCase.jsx'

const postEvents = vi.fn().mockResolvedValue({ ok: true })
const createSession = vi.fn().mockResolvedValue({ id: 'chat-session-1' })
const getStudyCase = vi.fn()
const getRecallOptions = vi.fn().mockResolvedValue({ options: [{ id: 'opt-a', text: 'Option A' }] })

vi.mock('../api/studyClient.js', () => ({
  getStudyCase: (...args) => getStudyCase(...args),
  postEvents: (...args) => postEvents(...args),
  getRecallOptions: (...args) => getRecallOptions(...args),
  studyChatApi: {
    createSession: (...args) => createSession(...args),
  },
}))

vi.mock('./ChatInterface.jsx', () => ({
  default: ({ studySessionId }) => <div data-testid="study-chat-mock">chat:{studySessionId}</div>,
}))

const findings = [
  {
    id: 'f1',
    claim: 'Continue aromatase-inhibitor therapy.',
    evidence_class: 'documented',
    evidence_level: 'B',
    citation: { id: 'SYN-1', url: 'https://example.org/f1', name: 'Ref' },
  },
]

const tasks = {
  evidence_lookup: { question: 'What guideline applies?' },
  trial_match: { question: 'Which trial?', region: 'US', max_answers: 2 },
  decision_rationale: { prompt: 'Why this decision?' },
}

function diffCasePayload() {
  return {
    unreviewed: false,
    case: {
      ...baseCaseFields(),
      arm: 'athena_full',
      reported_changes: [{ kind: 'new_alteration', summary: 'ESR1', triggering_event: 'u1' }],
      reported_supersessions: [
        { finding_id: 'f1', broken_assumption: 'no ESR1', triggering_event: 'u1', note: 'Note' },
      ],
      questions: [{ id: 'q1', text: 'What options remain?' }],
      tasks,
    },
  }
}

function baseCaseFields() {
  return {
    case_id: 'c1',
    label: 'Case one',
    cancer_type: 'Breast',
    age_years: 58,
    stage: 'IV',
    baseline_events: [],
    update_events: [],
    findings,
    decision_prompt: 'Next step?',
    decision_options: [
      { id: 'a', text: 'Continue unchanged' },
      { id: 'b', text: 'Change therapy' },
    ],
    reported_changes: [],
    reported_supersessions: [],
    questions: [],
  }
}

function usualCasePayload() {
  return {
    unreviewed: false,
    case: {
      ...baseCaseFields(),
      arm: 'usual_care',
      tasks,
    },
  }
}

function matchMediaDesktop() {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: query.includes('max-width') ? false : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

function renderEnrolled(item) {
  return render(
    <StudyCase
      participantId="P1"
      item={item}
      position={1}
      total={2}
      unreviewed={false}
      onDone={() => {}}
      enrolled
    />,
  )
}

async function waitForCaseLoaded() {
  await waitFor(() => expect(screen.getByText(/Case 1 of 2/)).toBeInTheDocument())
}

async function startTasks() {
  fireEvent.click(screen.getByRole('button', { name: /start tasks/i }))
  await waitFor(() => expect(screen.getByText(/Evidence lookup/i)).toBeInTheDocument())
}

async function submitEvidenceTask() {
  fireEvent.change(screen.getByLabelText(/your answer/i), { target: { value: 'My answer' } })
  const slider = screen.getByRole('slider')
  fireEvent.change(slider, { target: { value: '70' } })
  fireEvent.pointerUp(slider)
  fireEvent.click(screen.getByRole('button', { name: /^Continue$/i }))
  await waitFor(() => expect(screen.getByText(/Trial matching/i)).toBeInTheDocument())
}

describe('StudyCase enrolled layout', () => {
  beforeEach(() => {
    postEvents.mockClear()
    createSession.mockClear()
    getStudyCase.mockReset()
    matchMediaDesktop()
  })

  it('athena_full keeps diff view and chat after T1 with one createSession', async () => {
    getStudyCase.mockResolvedValue(diffCasePayload())
    renderEnrolled({ case_id: 'c1', arm: 'athena_full' })
    await waitForCaseLoaded()
    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1))

    expect(screen.getByText(/1 change/i)).toBeInTheDocument()
    expect(screen.getByTestId('study-chat-mock')).toHaveTextContent('chat:chat-session-1')

    await startTasks()
    await submitEvidenceTask()

    expect(screen.getByText(/1 change/i)).toBeInTheDocument()
    expect(screen.getByTestId('study-chat-mock')).toHaveTextContent('chat:chat-session-1')
    expect(createSession).toHaveBeenCalledTimes(1)
  })

  it('usual_care keeps findings and sources logger during tasks', async () => {
    getStudyCase.mockResolvedValue(usualCasePayload())
    renderEnrolled({ case_id: 'c1', arm: 'usual_care' })
    await waitForCaseLoaded()

    expect(screen.getByText(/Continue aromatase/i)).toBeInTheDocument()
    expect(screen.getByText(/Sources I used/i)).toBeInTheDocument()

    await startTasks()
    expect(screen.getByText(/Continue aromatase/i)).toBeInTheDocument()
    expect(screen.getByText(/Sources I used/i)).toBeInTheDocument()
    expect(screen.getByText(/Evidence lookup/i)).toBeInTheDocument()
  })

  it('recall step does not render case content', async () => {
    getStudyCase.mockResolvedValue(usualCasePayload())
    renderEnrolled({ case_id: 'c1', arm: 'usual_care' })
    await waitForCaseLoaded()

    await startTasks()
    await submitEvidenceTask()
    fireEvent.change(screen.getByLabelText(/Trial ID 1/i), { target: { value: 'NCT1' } })
    const trialSlider = screen.getByRole('slider')
    fireEvent.change(trialSlider, { target: { value: '60' } })
    fireEvent.pointerUp(trialSlider)
    fireEvent.click(screen.getByRole('button', { name: /^Continue$/i }))

    await waitFor(() => expect(screen.getByText(/Your assessment/i)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('radio', { name: /Valid and supported/i }))
    const assessSlider = screen.getByRole('slider')
    fireEvent.change(assessSlider, { target: { value: '80' } })
    fireEvent.pointerUp(assessSlider)
    fireEvent.click(screen.getByRole('button', { name: /^Continue$/i }))

    await waitFor(() => expect(screen.getByText(/Clinical decision/i)).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText(/Change therapy/i))
    fireEvent.change(document.querySelector('.study-assessment textarea'), { target: { value: 'Because X' } })
    fireEvent.click(screen.getByRole('button', { name: /^Continue$/i }))

    await waitFor(() => expect(screen.getByText(/About that case/i)).toBeInTheDocument())
    screen.getAllByRole('slider').forEach((s) => {
      fireEvent.change(s, { target: { value: '50' } })
      fireEvent.pointerUp(s)
    })
    fireEvent.click(screen.getByRole('button', { name: /^Continue$/i }))

    await waitFor(() => expect(screen.getByText(/What changed/i)).toBeInTheDocument())
    expect(screen.queryByTestId('enrolled-layout')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/Sources I used/i)).not.toBeInTheDocument())
    expect(screen.queryByText(/Continue aromatase/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Option A/i)).toBeInTheDocument()
  })
})