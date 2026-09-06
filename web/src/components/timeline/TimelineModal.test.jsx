import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import TimelineModal from './TimelineModal.jsx'
import * as chatClient from '../../api/chatClient.js'

const bundle = {
  events: [
    { date: '2024-01-01', end_date: null, category: 'Treatments', subcategory: 'Chemo', group: null, title: 'Cisplatin', dose: '75mg/m2', condition_track: null },
  ],
  mrd: [{ date: '2024-01-01', assay: 'signatera_genome', value: null, kind: 'not_detected' }],
  cytometry: [{ date: '2024-01-01', category: 'immune', measurement: 'CD8 T cells', short_name: 'CD8 T cells', unit: '%', value: 12.3 }],
  lab_results: [
    { date: '2024-01-01', category: 'CBC', measurement: 'Hemoglobin', test_name: 'Hemoglobin', panel_name: 'CBC', unit: 'g/dL', value: 13.5, reference_low: 12, reference_high: 16, flag: '', out_of_range: false },
  ],
}

describe('TimelineModal (chat-embedded Patient Timeline)', () => {
  it('fetches the unscoped reference timeline and renders it, since chat sessions have no case', async () => {
    vi.spyOn(chatClient, 'getReferenceTimeline').mockResolvedValue(bundle)

    render(<TimelineModal onClose={() => {}} />)

    expect(screen.getByText('Patient Timeline')).toBeInTheDocument()
    // Event titles only render in the click-to-reveal detail panel (see
    // TimelineChart.jsx), so assert on what's actually visible on load: the
    // category legend and the measurement explorers' rows.
    await waitFor(() => expect(screen.getByText(/Treatments \(1\)/)).toBeInTheDocument())
    expect(screen.getByText(/Hemoglobin/)).toBeInTheDocument()
  })

  it('calls onClose when the backdrop or close button is clicked', async () => {
    vi.spyOn(chatClient, 'getReferenceTimeline').mockResolvedValue(bundle)
    const onClose = vi.fn()

    const { container } = render(<TimelineModal onClose={onClose} />)
    await waitFor(() => expect(screen.getByText(/Treatments \(1\)/)).toBeInTheDocument())

    fireEvent.click(container.querySelector('.graph-close-btn'))
    expect(onClose).toHaveBeenCalledTimes(1)

    fireEvent.click(container.querySelector('.graph-modal-backdrop'))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('shows an error state instead of a blank modal when the fetch fails', async () => {
    vi.spyOn(chatClient, 'getReferenceTimeline').mockRejectedValue(new Error('/api/timeline returned 500'))

    render(<TimelineModal onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText(/Timeline query error/)).toBeInTheDocument())
  })
})
