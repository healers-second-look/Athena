/** Minimal safe markdown: headings, paragraphs, lists, bold — no raw HTML. */

function renderInline(text) {
  const parts = []
  const re = /\*\*([^*]+)\*\*/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    parts.push(<strong key={`${m.index}-b`}>{m[1]}</strong>)
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length ? parts : text
}

export default function SimpleMarkdown({ source }) {
  const lines = (source || '').split('\n')
  const nodes = []
  let listItems = null

  const flushList = () => {
    if (listItems?.length) {
      nodes.push(
        <ul key={`ul-${nodes.length}`}>
          {listItems.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ul>,
      )
      listItems = null
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      continue
    }
    if (trimmed.startsWith('### ')) {
      flushList()
      nodes.push(<h3 key={i}>{renderInline(trimmed.slice(4))}</h3>)
    } else if (trimmed.startsWith('## ')) {
      flushList()
      nodes.push(<h2 key={i}>{renderInline(trimmed.slice(3))}</h2>)
    } else if (trimmed.startsWith('# ')) {
      flushList()
      nodes.push(<h1 key={i}>{renderInline(trimmed.slice(2))}</h1>)
    } else if (trimmed.startsWith('- ')) {
      if (!listItems) listItems = []
      listItems.push(trimmed.slice(2))
    } else {
      flushList()
      nodes.push(<p key={i}>{renderInline(trimmed)}</p>)
    }
  }
  flushList()

  return <div className="consent-markdown">{nodes}</div>
}