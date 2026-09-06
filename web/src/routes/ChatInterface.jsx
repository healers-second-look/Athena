import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  createSession,
  getAttachments,
  getContexts,
  getModels,
  getSession,
  sendTurn,
  updateSession,
} from '../api/chatClient.js'
import GraphViewer from '../components/GraphViewer.jsx'
import TimelineModal from '../components/timeline/TimelineModal.jsx'

export default function ChatInterface() {
  const { id } = useParams()
  const navigate = useNavigate()
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Session state
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(false)
  const [input, setInput] = useState('')
  const [error, setError] = useState(null)

  // Catalog state
  const [models, setModels] = useState([])
  const [attachments, setAttachments] = useState([])
  const [contexts, setContexts] = useState([])

  // Selected turn for details panel
  const [selectedTurn, setSelectedTurn] = useState(null)

  // Phase 5 Graph Viewer state
  const [activeGraphContext, setActiveGraphContext] = useState(null)

  // Patient Timeline modal state
  const [showTimeline, setShowTimeline] = useState(false)

  // Load catalogs on mount
  useEffect(() => {
    Promise.all([getModels(), getAttachments(), getContexts()])
      .then(([m, a, c]) => {
        setModels(m)
        setAttachments(a)
        setContexts(c)
      })
      .catch(() => {
        setModels([
          { id: 'mock-outline', label: 'Athena Outline (offline)', available: true },
          { id: 'mock-terse', label: 'Athena Terse (offline)', available: true },
        ])
        setAttachments([
          { id: 'variant-normalizer', label: 'Variant normalizer', kind: 'plugin' },
          { id: 'citation-guard', label: 'Citation guard', kind: 'plugin' },
          { id: 'evidence-grader', label: 'Evidence grader', kind: 'skill' },
        ])
      })
  }, [])

  // Create or load session
  useEffect(() => {
    if (id === 'new') {
      createSession()
        .then((s) => navigate(`/chat/${s.id}`, { replace: true }))
        .catch((err) => setError(err.message))
    } else if (id) {
      getSession(id)
        .then((s) => {
          setSession(s)
          // Pre-select latest assistant turn for right drawer if history exists
          const lastAssistant = [...(s.history || [])].reverse().find((m) => m.role === 'assistant')
          if (lastAssistant) {
            setSelectedTurn({
              entities: lastAssistant.entities,
              notes: lastAssistant.notes,
              context_lines: lastAssistant.context_lines,
              sources: lastAssistant.sources,
            })
          }
        })
        .catch((err) => setError(err.message))
    }
  }, [id, navigate])

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [session?.history?.length])

  // Send message
  const handleSend = useCallback(async () => {
    if (!input.trim() || !session || loading) return
    const msg = input.trim()
    setInput('')
    setLoading(true)
    setError(null)

    // Optimistic user message
    setSession((prev) => ({
      ...prev,
      history: [
        ...prev.history,
        { id: 'temp', role: 'user', content: msg, timestamp: Date.now() / 1000 },
      ],
    }))

    try {
      const result = await sendTurn(session.id, msg)
      setSession((prev) => ({
        ...prev,
        history: [
          ...prev.history.filter((m) => m.id !== 'temp'),
          result.user_message,
          result.assistant_message,
        ],
      }))
      setSelectedTurn(result.turn)
    } catch (err) {
      setError(err.message)
      setSession((prev) => ({
        ...prev,
        history: prev.history.filter((m) => m.id !== 'temp'),
      }))
    } finally {
      setLoading(false)
    }
  }, [input, session, loading])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Config updates
  const handleModelChange = async (modelId) => {
    if (!session) return
    try {
      const updated = await updateSession(session.id, { model_id: modelId })
      setSession(updated)
    } catch (err) { setError(err.message) }
  }

  const handleAttachmentToggle = async (attachmentId) => {
    if (!session) return
    const current = session.attachment_ids || []
    const next = current.includes(attachmentId)
      ? current.filter((a) => a !== attachmentId)
      : [...current, attachmentId]
    try {
      const updated = await updateSession(session.id, { attachment_ids: next })
      setSession(updated)
    } catch (err) { setError(err.message) }
  }

  const handleContextChange = async (contextId) => {
    if (!session) return
    try {
      const updated = await updateSession(session.id, { context_id: contextId || null })
      setSession(updated)
    } catch (err) { setError(err.message) }
  }

  const handleNewChat = async () => {
    try {
      const s = await createSession()
      navigate(`/chat/${s.id}`)
    } catch (err) { setError(err.message) }
  }

  const modes = attachments.filter((a) => a.kind === 'mode')
  const plugins = attachments.filter((a) => a.kind !== 'mode')

  const activeMode = modes.find((m) =>
    (session?.attachment_ids || []).includes(m.id)
  )

  const handleModeChange = async (modeId) => {
    if (!session) return
    const nonModes = (session.attachment_ids || []).filter(
      (id) => !modes.some((m) => m.id === id)
    )
    const next = modeId ? [...nonModes, modeId] : nonModes
    try {
      const updated = await updateSession(session.id, { attachment_ids: next })
      setSession(updated)
    } catch (err) { setError(err.message) }
  }

  // Render assistant content with clickable citation tags [1], [2]
  const renderMessageContent = (content, sources = []) => {
    return content.split('\n').map((line, i) => {
      if (line.startsWith('## '))
        return (
          <h3 key={i} style={{ fontFamily: 'Newsreader, serif', fontWeight: 500, fontSize: 18, marginBottom: 8 }}>
            {line.replace('## ', '')}
          </h3>
        )
      if (line.startsWith('### '))
        return (
          <h4 key={i} style={{ fontWeight: 600, fontSize: 14, margin: '12px 0 4px', color: 'var(--sage-deep)' }}>
            {line.replace('### ', '')}
          </h4>
        )

      // Replace bracketed citations like [1], [2] with clickable badges
      const parts = line.split(/(\[\d+\])/g)
      const formattedParts = parts.map((part, pIdx) => {
        const match = part.match(/\[(\d+)\]/)
        if (match) {
          const citationIdx = parseInt(match[1], 10)
          const src = sources.find((s) => s.citation_index === citationIdx)
          return (
            <span
              key={pIdx}
              className="citation-pill"
              title={src ? `${src.title} (${src.evidence_level})` : `Citation ${citationIdx}`}
              onClick={(e) => {
                e.stopPropagation()
                if (src?.citation_url) window.open(src.citation_url, '_blank')
              }}
            >
              [{citationIdx}]
            </span>
          )
        }
        return part
      })

      if (line.startsWith('- ')) {
        return (
          <p key={i} style={{ paddingLeft: 16, fontSize: 14 }}>
            • {formattedParts}
          </p>
        )
      }
      if (line.trim()) {
        return <p key={i}>{formattedParts}</p>
      }
      return null
    })
  }

  if (!session && id !== 'new') {
    return (
      <div className="chat-layout">
        <div className="empty-state" style={{ flex: 1 }}>
          <span className="material-symbols-outlined">hourglass_empty</span>
          <h2>{error ? 'Connection Error' : 'Loading...'}</h2>
          <p>
            {error
              ? 'Start the API server with: uvicorn secondlook.api.app:create_app --reload'
              : 'Connecting to session...'}
          </p>
          {error && (
            <button className="btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/chat')}>
              Back to Landing
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="chat-layout">
      {/* Left Sidebar */}
      <aside className="chat-sidebar">
        <div className="sidebar-brand" onClick={() => navigate('/chat')} style={{ cursor: 'pointer' }}>
          <span className="material-symbols-outlined" style={{ fontSize: 28, color: 'var(--sage-deep)' }}>
            neurology
          </span>
          <span className="brand-name">Athena</span>
        </div>

        <div className="sidebar-new-chat">
          <button className="btn-new-chat" onClick={handleNewChat}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>add</span>
            New Chat
          </button>
        </div>

        <div className="sidebar-scroll">
          {/* Model selector */}
          <div className="config-section">
            <label className="section-label">Model (Phase 2)</label>
            <select
              className="config-select"
              value={session?.model_id || 'mock-outline'}
              onChange={(e) => handleModelChange(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          {/* Mode */}
          <div className="config-section">
            <label className="section-label">Mode (Phase 3)</label>
            <div className="mode-group">
              {modes.map((m) => (
                <label key={m.id} className={`mode-option ${activeMode?.id === m.id ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="mode"
                    checked={activeMode?.id === m.id}
                    onChange={() => handleModeChange(m.id)}
                  />
                  {m.label}
                </label>
              ))}
            </div>
          </div>

          {/* Attachments */}
          <div className="config-section">
            <label className="section-label">Attachments (Phase 3)</label>
            <div className="attachment-chips">
              {plugins.map((p) => {
                const isActive = (session?.attachment_ids || []).includes(p.id)
                const color = p.id.includes('variant') ? 'apricot'
                  : p.id.includes('citation') ? 'periwinkle' : 'sage'
                return (
                  <span
                    key={p.id}
                    className={`chip ${color} ${isActive ? 'active' : 'inactive'}`}
                    onClick={() => handleAttachmentToggle(p.id)}
                  >
                    {p.label}
                  </span>
                )
              })}
            </div>
          </div>
        </div>

        {/* KG Context (Phase 4 & 5) */}
        <div className="sidebar-kg">
          <label className="section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
            Knowledge Graph
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>link</span>
          </label>
          <select
            className="config-select"
            value={session?.context_id || ''}
            onChange={(e) => handleContextChange(e.target.value)}
          >
            <option value="">No KG context</option>
            {contexts.map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>

          {/* Phase 5 Graph Visualizer Trigger */}
          <button
            className="btn-view-graph"
            onClick={() => setActiveGraphContext(session?.context_id || 'graph:secondlook_tier1')}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>account_tree</span>
            View FalkorDB Graph
          </button>
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="chat-main">
        <header className="chat-topbar">
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span className="topbar-title">Synthesis</span>
            <span className="topbar-model">
              {models.find((m) => m.id === session?.model_id)?.label || 'Athena Outline'}
            </span>
            {session?.context_id && (
              <span className="topbar-model" style={{ background: 'var(--apricot-wash)', color: '#5d412c' }}>
                KG: {session.context_id}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className="btn-view-graph"
              style={{ width: 'auto', margin: 0, padding: '4px 10px' }}
              onClick={() => setActiveGraphContext(session?.context_id || 'graph:secondlook_tier1')}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>account_tree</span>
              Explore Graph
            </button>
            <button
              className="btn-view-graph"
              style={{ width: 'auto', margin: 0, padding: '4px 10px' }}
              onClick={() => setShowTimeline(true)}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>timeline</span>
              Patient Timeline
            </button>
            {activeMode && (
              <span className="material-symbols-outlined" style={{ fontSize: 20, color: 'var(--sage)' }} title={activeMode.label}>
                verified_user
              </span>
            )}
          </div>
        </header>

        {/* Messages */}
        <div className="chat-messages">
          {(!session?.history?.length) && (
            <div className="empty-state">
              <span className="material-symbols-outlined">forum</span>
              <h2>Start a conversation</h2>
              <p>Ask about clinical evidence (e.g. <code>EGFR T790M</code> or <code>ETV6::NTRK3</code>), drug responses, or pathways.</p>
            </div>
          )}

          {session?.history?.map((msg) => (
            msg.role === 'user' ? (
              <div key={msg.id} className="msg-user">
                <div className="msg-user-bubble">{msg.content}</div>
              </div>
            ) : (
              <div
                key={msg.id}
                className="msg-assistant"
                onClick={() => setSelectedTurn({
                  entities: msg.entities,
                  notes: msg.notes,
                  context_lines: msg.context_lines,
                  sources: msg.sources,
                })}
              >
                <div className="msg-avatar">
                  <span className="material-symbols-outlined">auto_awesome</span>
                </div>
                <div className="msg-body">
                  {renderMessageContent(msg.content, msg.sources || [])}

                  {/* Entities & Attachment Notes */}
                  {((msg.entities && Object.keys(msg.entities).length > 0) || msg.notes?.length > 0) && (
                    <div className="msg-notes">
                      {msg.entities && Object.entries(msg.entities).map(([type, values]) =>
                        values.map((v) => (
                          <span
                            key={`${type}-${v}`}
                            className="msg-note entity"
                            style={{ cursor: 'pointer' }}
                            onClick={(e) => {
                              e.stopPropagation()
                              setActiveGraphContext(`gene:${v}`)
                            }}
                          >
                            {type}: {v} (Inspect)
                          </span>
                        ))
                      )}
                      {msg.notes?.slice(0, 2).map((note, i) => (
                        <span key={i} className="msg-note attachment">
                          <span className="material-symbols-outlined" style={{ fontSize: 12 }}>check_circle</span>
                          {note.split(' -> ')[0]}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          ))}

          {loading && (
            <div className="msg-assistant">
              <div className="msg-avatar">
                <span className="material-symbols-outlined" style={{ animation: 'spin 1s linear infinite' }}>sync</span>
              </div>
              <div className="msg-body loading-dots">
                <span /><span /><span />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="chat-input-area">
          <div className="chat-input-container">
            <div className="chat-input-box">
              <textarea
                ref={inputRef}
                className="chat-input"
                placeholder="Ask about clinical evidence (e.g. EGFR T790M or ETV6::NTRK3)..."
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <button
                className="btn-send"
                onClick={handleSend}
                disabled={!input.trim() || loading}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 20 }}>
                  arrow_upward
                </span>
              </button>
            </div>
            <p className="chat-disclaimer">
              Athena grounds synthesis in live CIViC and FalkorDB knowledge graph evidence.
            </p>
          </div>
        </div>
      </main>

      {/* Right Details Panel (Phases 3, 4, 6) */}
      <aside className="chat-details">
        <header className="details-header">
          <h2>Turn Details</h2>
        </header>
        <div className="details-scroll">
          {selectedTurn ? (
            <>
              {/* Entities Detected */}
              {selectedTurn.entities && Object.keys(selectedTurn.entities).length > 0 && (
                <section className="detail-section">
                  <h3>
                    <span className="material-symbols-outlined">scatter_plot</span>
                    Entities Detected
                  </h3>
                  <div className="entity-grid">
                    {Object.entries(selectedTurn.entities).map(([type, values]) =>
                      values.map((v) => (
                        <div
                          key={`${type}-${v}`}
                          className="entity-row"
                          style={{ cursor: 'pointer' }}
                          onClick={() => setActiveGraphContext(`gene:${v}`)}
                        >
                          <span className="entity-type">{type}</span>
                          <span className="entity-value">{v} ↗</span>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              )}

              <hr className="detail-divider" />

              {/* Phase 6 Sources Used */}
              <section className="detail-section">
                <h3>
                  <span className="material-symbols-outlined">menu_book</span>
                  Sources Used ({selectedTurn.sources?.length || 0})
                </h3>
                {selectedTurn.sources?.length > 0 ? (
                  <div>
                    {selectedTurn.sources.map((src) => (
                      <div key={src.id} className="source-card">
                        <div className="source-card-header">
                          <span className="source-idx">[{src.citation_index}]</span>
                          <span className="source-level-badge">Level {src.evidence_level}</span>
                        </div>
                        <div className="source-title">{src.title}</div>
                        <div className="source-summary">{src.summary}</div>
                        <a
                          href={src.citation_url}
                          target="_blank"
                          rel="noreferrer"
                          className="source-link"
                        >
                          PMID {src.pmid} ↗
                        </a>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: 12, color: 'var(--outline)' }}>
                    No retrieved sources attached to this turn.
                  </p>
                )}
              </section>

              <hr className="detail-divider" />

              {/* Trace */}
              {selectedTurn.notes?.length > 0 && (
                <section className="detail-section">
                  <h3>
                    <span className="material-symbols-outlined">extension</span>
                    Execution Trace
                  </h3>
                  {selectedTurn.notes.map((note, i) => (
                    <div key={i} className="trace-item">
                      <span className="material-symbols-outlined">check_circle</span>
                      <div>
                        <div className="trace-name">{note.split(' ')[0]}</div>
                        <div className="trace-detail">{note}</div>
                      </div>
                    </div>
                  ))}
                </section>
              )}
            </>
          ) : (
            <div className="empty-state" style={{ padding: 24 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 36, marginBottom: 8 }}>
                info
              </span>
              <p style={{ fontSize: 13 }}>
                Send a message to see entities, citations, and execution traces.
              </p>
            </div>
          )}
        </div>
      </aside>

      {/* Phase 5 Graph Visualizer Modal */}
      {activeGraphContext && (
        <GraphViewer
          contextId={activeGraphContext}
          onClose={() => setActiveGraphContext(null)}
        />
      )}

      {/* Patient Timeline Modal */}
      {showTimeline && <TimelineModal onClose={() => setShowTimeline(false)} />}

      {error && (
        <div style={{
          position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)',
          background: '#ffdad6', color: '#93000a', padding: '8px 16px',
          borderRadius: 8, fontSize: 13, zIndex: 100,
        }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: 8, cursor: 'pointer', background: 'none', border: 'none', fontWeight: 600 }}>✕</button>
        </div>
      )}
    </div>
  )
}
