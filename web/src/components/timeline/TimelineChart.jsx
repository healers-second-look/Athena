import { useMemo, useState } from 'react'

// Chronological swim-lane timeline -- one lane per event category, plus an
// MRD lane, markers positioned by real date along a shared horizontal axis.
// Plain SVG, no charting library (matches GraphViewer.jsx's precedent and
// this project's low-bandwidth-client budget -- see docs/performance-budget.md).
const CATEGORY_COLORS = {
  Treatments: { fill: '#9db2d6', stroke: '#4b5f7f' },
  Procedures: { fill: '#e7bfa4', stroke: '#8a6a4e' },
  Imaging: { fill: '#a8d5ba', stroke: '#3f6750' },
}
const MRD_COLOR = { fill: '#d6a8c9', stroke: '#7f4b6c' }

const WIDTH = 900
const LANE_HEIGHT = 46
const MARGIN = { top: 20, right: 24, bottom: 34, left: 110 }

function toDate(s) {
  return new Date(s + 'T00:00:00Z')
}

export default function TimelineChart({ events, mrd }) {
  const [selected, setSelected] = useState(null)

  const lanes = useMemo(() => {
    const cats = [...new Set(events.map((e) => e.category))].sort()
    return mrd.length ? [...cats, 'MRD'] : cats
  }, [events, mrd])

  const { minTime, maxTime } = useMemo(() => {
    const dates = [
      ...events.flatMap((e) => [e.date, e.end_date].filter(Boolean)),
      ...mrd.map((m) => m.date),
    ].map((d) => toDate(d).getTime())
    if (!dates.length) return { minTime: 0, maxTime: 1 }
    return { minTime: Math.min(...dates), maxTime: Math.max(...dates) }
  }, [events, mrd])

  const height = MARGIN.top + MARGIN.bottom + lanes.length * LANE_HEIGHT
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right
  const span = Math.max(maxTime - minTime, 1)
  const x = (dateStr) => MARGIN.left + ((toDate(dateStr).getTime() - minTime) / span) * plotWidth
  const laneY = (cat) => MARGIN.top + lanes.indexOf(cat) * LANE_HEIGHT + LANE_HEIGHT / 2

  const yearTicks = useMemo(() => {
    const startYear = new Date(minTime).getUTCFullYear()
    const endYear = new Date(maxTime).getUTCFullYear()
    const ticks = []
    for (let y = startYear; y <= endYear; y++) {
      const t = Date.UTC(y, 0, 1)
      if (t >= minTime && t <= maxTime) ticks.push({ year: y, xPos: x(`${y}-01-01`) })
    }
    return ticks
  }, [minTime, maxTime])

  if (!lanes.length) return <p className="muted">No events in the selected categories.</p>

  return (
    <div className="timeline-chart-wrap">
      <div className="timeline-chart-scroll">
        <svg
          viewBox={`0 0 ${WIDTH} ${height}`}
          width="100%"
          role="img"
          aria-label="Chronological patient timeline"
        >
          {lanes.map((cat, i) => (
            <g key={cat}>
              <rect
                x={0}
                y={MARGIN.top + i * LANE_HEIGHT}
                width={WIDTH}
                height={LANE_HEIGHT}
                className={i % 2 === 0 ? 'timeline-lane-even' : 'timeline-lane-odd'}
              />
              <text x={8} y={laneY(cat)} dy="0.35em" className="timeline-lane-label">
                {cat}
              </text>
            </g>
          ))}

          {yearTicks.map(({ year, xPos }) => (
            <g key={year}>
              <line
                x1={xPos}
                x2={xPos}
                y1={MARGIN.top}
                y2={height - MARGIN.bottom}
                className="timeline-year-gridline"
              />
              <text x={xPos} y={height - MARGIN.bottom + 16} className="timeline-year-label">
                {year}
              </text>
            </g>
          ))}

          {events.map((e, i) => {
            const color = CATEGORY_COLORS[e.category] || CATEGORY_COLORS.Procedures
            const cy = laneY(e.category)
            const isSelected = selected?.kind === 'event' && selected.index === i
            if (e.end_date && e.end_date !== e.date) {
              const x1 = x(e.date)
              const x2 = x(e.end_date)
              return (
                <rect
                  key={i}
                  x={Math.min(x1, x2)}
                  y={cy - 6}
                  width={Math.max(Math.abs(x2 - x1), 3)}
                  height={12}
                  rx={4}
                  fill={color.fill}
                  stroke={color.stroke}
                  strokeWidth={isSelected ? 2 : 1}
                  className="timeline-marker"
                  onClick={() => setSelected({ kind: 'event', index: i, data: e })}
                />
              )
            }
            return (
              <circle
                key={i}
                cx={x(e.date)}
                cy={cy}
                r={isSelected ? 7 : 5}
                fill={color.fill}
                stroke={color.stroke}
                strokeWidth={isSelected ? 2 : 1}
                className="timeline-marker"
                onClick={() => setSelected({ kind: 'event', index: i, data: e })}
              />
            )
          })}

          {mrd.map((m, i) => {
            const isSelected = selected?.kind === 'mrd' && selected.index === i
            return (
              <circle
                key={i}
                cx={x(m.date)}
                cy={laneY('MRD')}
                r={isSelected ? 6 : 4}
                fill={MRD_COLOR.fill}
                stroke={MRD_COLOR.stroke}
                strokeWidth={isSelected ? 2 : 1}
                className="timeline-marker"
                onClick={() => setSelected({ kind: 'mrd', index: i, data: m })}
              />
            )
          })}
        </svg>
      </div>

      <div className="timeline-detail-panel">
        {selected ? (
          selected.kind === 'event' ? (
            <>
              <span className={`chip-inline cat-${selected.data.category.toLowerCase()}`}>
                {selected.data.category}
              </span>
              {/* `title` is legitimately blank for some real events (Imaging
                  rows where only subcategory/group was ever recorded in the
                  source data) -- fall back rather than render nothing. */}
              <strong>{selected.data.title || selected.data.subcategory || selected.data.group}</strong>
              {selected.data.title && selected.data.subcategory ? (
                <span> — {selected.data.subcategory}</span>
              ) : null}
              <div className="small muted">
                {selected.data.date}
                {selected.data.end_date && selected.data.end_date !== selected.data.date
                  ? ` – ${selected.data.end_date}`
                  : null}
                {selected.data.dose ? ` · ${selected.data.dose}` : null}
              </div>
            </>
          ) : (
            <>
              <span className="chip-inline cat-mrd">MRD</span>
              <strong>{selected.data.assay}</strong>
              <div className="small muted">
                {selected.data.date} ·{' '}
                {selected.data.value ?? selected.data.kind.replace(/_/g, ' ')}
              </div>
            </>
          )
        ) : (
          <span className="muted small">Click any marker for details.</span>
        )}
      </div>
    </div>
  )
}
