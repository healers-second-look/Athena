// Shared i18n string lookup and plain-language generation.
//
// Read from web/fixtures/strings.json -- the exact same catalogue read by
// secondlook/web/fixtures.py, ensuring the client and the no-JS fallback
// never drift in their translations or plain-language wording.

import stringsFixture from '../fixtures/strings.json'

export function getStrings(lang = 'en') {
  return stringsFixture[lang] || stringsFixture.en
}

export function t(key, lang = 'en') {
  const bundle = getStrings(lang)
  const parts = key.split('.')
  let val = bundle
  for (const p of parts) {
    val = val?.[p]
    if (val === undefined) break
  }
  return val !== undefined ? val : key
}

/**
 * Deterministically derive a plain-language summary from a finding's record.
 * Never calls an LLM; strictly renders existing fields.
 */
export function derivePlainLanguage(finding, lang = 'en') {
  const strings = getStrings(lang)
  const pl = strings.plain_language
  const klass = finding.evidence_class
  const source = finding.source || {}

  let warrant = ''
  if (klass === 'documented') {
    const srcName = source.name || source.citation_id || 'Medical literature'
    const level = finding.evidence_level || 'standard'
    warrant = pl.documented_warrant.replace('{source}', srcName).replace('{level}', level)
  } else if (klass === 'computed') {
    const method = source.method || 'Computational model'
    const version = source.version || '1.0'
    warrant = pl.computed_warrant.replace('{method}', method).replace('{version}', version)
  } else if (klass === 'regulatory') {
    const instrument = source.instrument || 'Regulatory agency'
    warrant = pl.regulatory_warrant.replace('{instrument}', instrument)
  } else if (klass === 'contextual') {
    warrant = pl.contextual_warrant
  }

  return {
    title: pl.title,
    warrant,
    claim: finding.claim,
    caveats: finding.caveats || [],
    caveatHeading: pl.caveat_heading,
    toggleButton: pl.toggle_button,
  }
}
