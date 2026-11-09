"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ChartSpec, CodeModeResult } from "@/lib/types";
import { formatCell, formatValue } from "@/lib/format";

const PALETTE = ["#16803c", "#2f9e58", "#5aaf75", "#126b38", "#7bc492", "#3f8053", "#a0d4ae", "#245c37"];

function Chart({ spec }: { spec: ChartSpec }) {
  // Guard against malformed model output: only render when shapes line up.
  const labels = Array.isArray(spec.labels) ? spec.labels : [];
  const series = Array.isArray(spec.series) ? spec.series : [];
  if (!labels.length || !series.length) return null;
  const data = labels.map((label, i) => {
    const row: Record<string, string | number> = { label };
    series.forEach((s) => (row[s.name] = Number(s.data?.[i] ?? 0)));
    return row;
  });
  const axisProps = { stroke: "var(--muted)", fontSize: 12 } as const;

  return (
    <div className="card">
      <h3>Chart</h3>
      <div style={{ width: "100%", height: 320 }}>
        <ResponsiveContainer>
          {spec.type === "pie" ? (
            <PieChart>
              <Pie data={data} dataKey={series[0].name} nameKey="label" outerRadius={110} label>
                {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          ) : spec.type === "line" ? (
            <LineChart data={data}>
              <CartesianGrid stroke="var(--border)" />
              <XAxis dataKey="label" {...axisProps} />
              <YAxis {...axisProps} />
              <Tooltip />
              {series.length > 1 && <Legend />}
              {series.map((s, i) => (
                <Line key={s.name} dataKey={s.name} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data}>
              <CartesianGrid stroke="var(--border)" />
              <XAxis dataKey="label" {...axisProps} />
              <YAxis {...axisProps} />
              <Tooltip />
              {series.length > 1 && <Legend />}
              {series.map((s, i) => (
                <Bar key={s.name} dataKey={s.name} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {(spec.x_label || spec.y_label) && (
        <p className="muted small">{[spec.y_label, spec.x_label].filter(Boolean).join(" by ")}</p>
      )}
    </div>
  );
}

export default function ResultView({ result }: { result: CodeModeResult }) {
  const known = ["title", "summary", "kpis", "chart", "table", "assumptions"];
  const hasStructure = known.some((k) => result[k] != null);
  const isEmpty = result.total === 0 && !result.table?.rows?.length && !result.chart;

  return (
    <div className="stack">
      <div className="card">
        {result.title && <h2>{result.title}</h2>}
        {result.summary && <p className="summary">{result.summary}</p>}
        {isEmpty && <span className="badge">No matching data</span>}
        {!hasStructure && <pre className="json">{JSON.stringify(result, null, 2)}</pre>}
      </div>

      {!!result.kpis?.length && (
        <div className="kpis">
          {result.kpis.map((k, i) => (
            <div className="kpi" key={i}>
              <div className="kpi-label">{k.label}</div>
              <div className="kpi-value">{formatValue(k.value, k.unit)}</div>
            </div>
          ))}
        </div>
      )}

      {result.chart && <Chart spec={result.chart} />}

      {!!result.table?.rows?.length && (
        <div className="card">
          <h3>Data</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>{result.table.columns.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {result.table.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className={typeof cell === "number" ? "num" : ""}>
                        {formatCell(cell, result.table!.columns[j] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!!result.assumptions?.length && (
        <div className="card">
          <h3>Assumptions</h3>
          <ul>{result.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
