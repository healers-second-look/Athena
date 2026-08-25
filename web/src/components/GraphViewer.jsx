import { useEffect, useMemo, useRef, useState } from 'react'
import { getContextGraph } from '../api/chatClient.js'

// Pastel colors matching our Stitch design system
const TYPE_COLORS = {
  Gene: { bg: '#c1edd0', stroke: '#3f6750', text: '#002112' },
  Variant: { bg: '#c3d8fe', stroke: '#4b5f7f', text: '#031c38' },
  Drug: { bg: '#d5e3ff', stroke: '#334866', text: '#031c38' },
  Disease: { bg: '#ffdcc5', stroke: '#775842', text: '#2c1606' },
  EvidenceItem: { bg: '#eae8e3', stroke: '#717973', text: '#1b1c19' },
  StructuralSignal: { bg: '#e7bfa4', stroke: '#bd987f', text: '#4a311d' },
  Node: { bg: '#f0eee9', stroke: '#717973', text: '#1b1c19' },
}

export default function GraphViewer({ contextId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [activeTab, setActiveTab] = useState('graph') // 'graph' | 'cypher'

  const svgRef = useRef(null)

  useEffect(() => {
    if (!contextId) return
    setLoading(true)
    getContextGraph(contextId)
      .then((res) => {
        setData(res)
        if (res.nodes?.length) setSelectedNode(res.nodes[0])
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [contextId])

  // Simple deterministic circular/hierarchical layout for the SVG
  const nodePositions = useMemo(() => {
    if (!data?.nodes?.length) return {}
    const width = 640
    const height = 440
    const centerX = width / 2
    const centerY = height / 2
    const pos = {}

    // Group by node type for structured radial placement
    const groups = {}
    data.nodes.forEach((n) => {
      groups[n.type] = groups[n.type] || []
      groups[n.type].push(n)
    })

    const types = Object.keys(groups)
    types.forEach((type, typeIdx) => {
      const radius = 90 + typeIdx * 70
      const list = groups[type]
      list.forEach((n, idx) => {
        const angle = (idx / list.length) * 2 * Math.PI + (typeIdx * Math.PI) / 4
        pos[n.id] = {
          x: Math.max(50, Math.min(width - 50, centerX + radius * Math.cos(angle))),
          y: Math.max(40, Math.min(height - 40, centerY + radius * Math.sin(angle))),
        }
      })
    })

    return pos
  }, [data])

  return (
    <div className="graph-modal-backdrop" onClick={onClose}>
      <div className="graph-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="graph-header">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined" style={{ color: 'var(--sage-dark)', fontSize: 24 }}>
              account_tree
            </span>
            <div>
              <h2 className="graph-title">Knowledge Graph Subgraph</h2>
              <p className="graph-subtitle">Context: <code>{contextId}</code></p>
            </div>
          </div>
          <div className="graph-tabs">
            <button
              className={`graph-tab ${activeTab === 'graph' ? 'active' : ''}`}
              onClick={() => setActiveTab('graph')}
            >
              Visual Graph ({data?.nodes?.length || 0} nodes)
            </button>
            <button
              className={`graph-tab ${activeTab === 'cypher' ? 'active' : ''}`}
              onClick={() => setActiveTab('cypher')}
            >
              Live Cypher Query
            </button>
            <button className="graph-close-btn" onClick={onClose}>
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="graph-body">
          {loading && (
            <div className="empty-state" style={{ height: 400 }}>
              <span className="material-symbols-outlined" style={{ animation: 'spin 1s linear infinite' }}>
                sync
              </span>
              <p>Querying FalkorDB graph...</p>
            </div>
          )}

          {error && (
            <div className="empty-state" style={{ height: 400, color: 'var(--alarm)' }}>
              <span className="material-symbols-outlined">error</span>
              <p>Graph query error: {error}</p>
            </div>
          )}

          {!loading && !error && activeTab === 'graph' && (
            <div className="graph-viz-container">
              {/* SVG Canvas */}
              <div className="graph-canvas">
                <svg
                  ref={svgRef}
                  viewBox="0 0 640 440"
                  className="w-full h-full"
                  style={{ background: 'var(--surface-low)' }}
                >
                  <defs>
                    <marker
                      id="arrow"
                      viewBox="0 0 10 10"
                      refX="22"
                      refY="5"
                      markerWidth="6"
                      markerHeight="6"
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--outline)" />
                    </marker>
                  </defs>

                  {/* Edges */}
                  {data?.edges?.map((edge, i) => {
                    const src = nodePositions[edge.source]
                    const dst = nodePositions[edge.target]
                    if (!src || !dst) return null
                    const midX = (src.x + dst.x) / 2
                    const midY = (src.y + dst.y) / 2

                    return (
                      <g key={i}>
                        <line
                          x1={src.x}
                          y1={src.y}
                          x2={dst.x}
                          y2={dst.y}
                          stroke="var(--outline-light)"
                          strokeWidth="2"
                          markerEnd="url(#arrow)"
                        />
                        <text
                          x={midX}
                          y={midY - 4}
                          fontSize="9"
                          fill="var(--outline)"
                          textAnchor="middle"
                          fontFamily="Inter, sans-serif"
                        >
                          {edge.type}
                        </text>
                      </g>
                    )
                  })}

                  {/* Nodes */}
                  {data?.nodes?.map((node) => {
                    const pos = nodePositions[node.id]
                    if (!pos) return null
                    const style = TYPE_COLORS[node.type] || TYPE_COLORS.Node
                    const isSelected = selectedNode?.id === node.id

                    return (
                      <g
                        key={node.id}
                        transform={`translate(${pos.x}, ${pos.y})`}
                        onClick={() => setSelectedNode(node)}
                        style={{ cursor: 'pointer' }}
                      >
                        <circle
                          r={isSelected ? 24 : 18}
                          fill={style.bg}
                          stroke={isSelected ? 'var(--sage-dark)' : style.stroke}
                          strokeWidth={isSelected ? 3 : 1.5}
                        />
                        <text
                          dy=".3em"
                          fontSize="10"
                          fontWeight="600"
                          fill={style.text}
                          textAnchor="middle"
                          fontFamily="Inter, sans-serif"
                        >
                          {node.label.length > 8 ? `${node.label.slice(0, 7)}…` : node.label}
                        </text>
                        <text
                          dy="32"
                          fontSize="9"
                          fill="var(--ink-soft)"
                          textAnchor="middle"
                          fontFamily="Inter, sans-serif"
                        >
                          {node.type}
                        </text>
                      </g>
                    )
                  })}
                </svg>
              </div>

              {/* Node Inspector Sidebar */}
              <div className="node-inspector">
                <h3>Node Details</h3>
                {selectedNode ? (
                  <div className="inspector-content">
                    <div className="inspector-badge" style={{
                      backgroundColor: TYPE_COLORS[selectedNode.type]?.bg,
                      color: TYPE_COLORS[selectedNode.type]?.text,
                      border: `1px solid ${TYPE_COLORS[selectedNode.type]?.stroke}`,
                    }}>
                      {selectedNode.type}
                    </div>
                    <h4 className="inspector-label">{selectedNode.label}</h4>
                    
                    <div className="inspector-props">
                      <p className="props-title">Properties:</p>
                      {Object.entries(selectedNode.properties || {}).map(([k, v]) => (
                        <div key={k} className="prop-row">
                          <span className="prop-key">{k}:</span>
                          <span className="prop-val">{v}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-outline">Click any node to inspect properties.</p>
                )}
              </div>
            </div>
          )}

          {!loading && !error && activeTab === 'cypher' && (
            <div className="cypher-view">
              <h3>Exact Cypher Query Executed</h3>
              <pre className="cypher-code">
                <code>{data?.cypher}</code>
              </pre>
              {data?.params && (
                <div style={{ marginTop: 16 }}>
                  <h4>Query Parameters:</h4>
                  <pre className="cypher-code" style={{ marginTop: 8 }}>
                    <code>{JSON.stringify(data.params, null, 2)}</code>
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
