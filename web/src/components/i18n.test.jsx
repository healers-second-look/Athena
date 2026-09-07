import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PlainLanguageBox from './PlainLanguageBox.jsx'
import { derivePlainLanguage, getStrings, t } from '../i18n.js'
import findings from '../../fixtures/findings.json'

const TRIAL_ELIGIBILITY = 'f0000000-0000-4000-8000-000000000032'
const DOCUMENTED = 'f0000000-0000-4000-8000-000000000021'
const REGULATORY = 'f0000000-0000-4000-8000-000000000051'
const CONTEXTUAL = 'f0000000-0000-4000-8000-000000000061'

describe('Subsystem M: string externalisation and catalogue', () => {
  it('loads en and hi catalogues with required namespaces', () => {
    const en = getStrings('en')
    const hi = getStrings('hi')
    expect(en).toBeDefined()
    expect(hi).toBeDefined()
    expect(en.plain_language.title).toBe('Plain language explanation')
    expect(hi.plain_language.title).toBe('सरल भाषा में स्पष्टीकरण')
  })

  it('translates nested keys with fallback', () => {
    expect(t('labels.case_dashboard', 'en')).toBe('Case dashboard')
    expect(t('labels.case_dashboard', 'hi')).toBe('केस डैशबोर्ड')
    expect(t('non.existent.key', 'en')).toBe('non.existent.key')
  })
})

describe('Subsystem M: deterministic plain language derivation', () => {
  it('derives documented warrant without LLM drift', () => {
    const finding = findings[DOCUMENTED]
    const pl = derivePlainLanguage(finding, 'en')
    expect(pl.warrant).toMatch(/published medical evidence/i)
    expect(pl.claim).toBe(finding.claim)
  })

  it('derives computed warrant highlighting algorithmic calculation', () => {
    const finding = findings[TRIAL_ELIGIBILITY]
    const pl = derivePlainLanguage(finding, 'en')
    expect(pl.warrant).toMatch(/calculated prediction/i)
    expect(pl.warrant).toMatch(/not directly tested in a laboratory/i)
    expect(pl.caveats).toEqual(finding.caveats)
  })

  it('derives Hindi plain language correctly', () => {
    const finding = findings[DOCUMENTED]
    const pl = derivePlainLanguage(finding, 'hi')
    expect(pl.title).toBe('सरल भाषा में स्पष्टीकरण')
    expect(pl.warrant).toMatch(/चिकित्सा साक्ष्य/)
  })
})

describe('Subsystem M: PlainLanguageBox component', () => {
  it('renders explanation box with warrant and caveats', () => {
    const finding = findings[TRIAL_ELIGIBILITY]
    const { container } = render(<PlainLanguageBox finding={finding} lang="en" />)
    expect(screen.getByTestId('plain-language-box')).toBeInTheDocument()
    expect(screen.getByText(/Calculated prediction/)).toBeInTheDocument()
    // Computed cards must not have links in plain language box
    expect(container.querySelectorAll('a')).toHaveLength(0)
  })

  it('renders Hindi explanation box', () => {
    const finding = findings[REGULATORY]
    render(<PlainLanguageBox finding={finding} lang="hi" />)
    expect(screen.getByText('सरल भाषा में स्पष्टीकरण')).toBeInTheDocument()
  })

  it('returns null when finding is not provided', () => {
    const { container } = render(<PlainLanguageBox finding={null} />)
    expect(container.firstChild).toBeNull()
  })
})
