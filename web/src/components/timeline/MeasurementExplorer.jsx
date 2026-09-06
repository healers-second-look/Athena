import { useMemo, useState } from 'react'

// Flow Cytometry (1,110 rows) and Lab Results (5,016 rows) are both too
// dense to plot as individual timeline markers -- the reference site
// downloads them as separate TSVs for exactly that reason (four distinct
// data tracks, not one merged feed). This renders them as: pick one
// measurement, see its values over time as a small chart (when numeric)
// plus the underlying rows as a table.
const CHART_WIDTH = 640
const CHART_HEIGHT = 180
const MARGIN = { top: 12, right: 16, bottom: 24, left: 48 }

function parseNumeric(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export default function MeasurementExplorer({ rows, measurementKey, valueKey, emptyLabel }) {
  const measurements = useMemo(() => {
    const counts = new Map()
    for (const row of rows) {
      const key = row[measurementKey]
      if (!key) continue
      counts.set(key, (counts.get(key) || 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [rows, measurementKey])

  const [selected, setSelected] = useState(measurements[0]?.[0] || '')

  const selectedRows = useMemo(
    () =>
      rows
        .filter((r) => r[measurementKey] === selected)
        .sort((a, b) => a.date.localeCompare(b.date)),
    [rows, measurementKey, selected]
  )

  const numericPoints = useMemo(
    () =>
      selectedRows
        .map((r) => ({ date: r.date, value: parseNumeric(r[valueKey]) }))
        .filter((p) => p.value !== null),
    [selectedRows, valueKey]
  )

  const isChartable = numericPoints.length >= 2

  if (!rows.length) return <p className="muted">No {emptyLabel} data.</p>

  return (
    <div className="measurement-explorer">
      <label className="small muted">
        {emptyLabel} ({measurements.length} distinct, {rows.length} results total)
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {measurements.map(([name, count]) => (
            <option key={name} value={name}>
              {name} ({count})
            </option>
          ))}
        </select>
      </label>

      {isChartable && <MiniLineChart points={numericPoints} unit={selectedRows[0]?.unit} />}

      <div className="timeline-table-scroll">
        <table className="timeline-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Value</th>
              {selectedRows[0]?.reference_low !== undefined && <th>Reference range</th>}
              {selectedRows[0]?.flag !== undefined && <th>Flag</th>}
            </tr>
          </thead>
          <tbody>
            {selectedRows.slice(0, 200).map((r, i) => (
              <tr key={i} className={r.out_of_range ? 'lab-out-of-range' : undefined}>
                <td>{r.date}</td>
                <td>
                  {r[valueKey]}
                  {r.unit ? ` ${r.unit}` : ''}
                </td>
                {r.reference_low !== undefined && (
                  <td className="small muted">
                    {r.reference_low && r.reference_high
                      ? `${r.reference_low}–${r.reference_high}`
                      : '—'}
                  </td>
                )}
                {r.flag !== undefined && <td className="small">{r.flag || ''}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {selectedRows.length > 200 && (
          <p className="small muted">
            Showing the first 200 of {selectedRows.length} results for this measurement.
          </p>
        )}
      </div>
    </div>
  )
}

function MiniLineChart({ points, unit }) {
  const minTime = new Date(points[0].date).getTime()
  const maxTime = new Date(points[points.length - 1].date).getTime()
  const span = Math.max(maxTime - minTime, 1)
  const values = points.map((p) => p.value)
  const minV = Math.min(...values)
  const maxV = Math.max(...values)
  const vSpan = Math.max(maxV - minV, 1e-9)

  const plotW = CHART_WIDTH - MARGIN.left - MARGIN.right
  const plotH = CHART_HEIGHT - MARGIN.top - MARGIN.bottom
  const x = (d) => MARGIN.left + ((new Date(d).getTime() - minTime) / span) * plotW
  const y = (v) => MARGIN.top + plotH - ((v - minV) / vSpan) * plotH

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.date)} ${y(p.value)}`).join(' ')

  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      width="100%"
      className="measurement-chart"
      role="img"
      aria-label="Values over time"
    >
      <line
        x1={MARGIN.left}
        x2={MARGIN.left}
        y1={MARGIN.top}
        y2={CHART_HEIGHT - MARGIN.bottom}
        className="chart-axis"
      />
      <line
        x1={MARGIN.left}
        x2={CHART_WIDTH - MARGIN.right}
        y1={CHART_HEIGHT - MARGIN.bottom}
        y2={CHART_HEIGHT - MARGIN.bottom}
        className="chart-axis"
      />
      <text x={4} y={y(maxV)} dy="0.3em" className="chart-axis-label">
        {maxV.toFixed(1)}
      </text>
      <text x={4} y={y(minV)} dy="0.3em" className="chart-axis-label">
        {minV.toFixed(1)}
        {unit ? ` ${unit}` : ''}
      </text>
      <path d={path} className="chart-line" fill="none" />
      {points.map((p, i) => (
        <circle key={i} cx={x(p.date)} cy={y(p.value)} r={2.5} className="chart-point" />
      ))}
    </svg>
  )
}
