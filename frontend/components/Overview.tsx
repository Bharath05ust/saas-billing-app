"use client";

import { useEffect, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Overview as OverviewData } from "@/lib/types";
import { formatValue } from "@/lib/format";

const usd = (n: number) => formatValue(n, "usd");
const compact = (n: number) => new Intl.NumberFormat("en-US", { notation: "compact", style: "currency", currency: "USD" }).format(n);

/** Live portfolio dashboard: deterministic numbers straight from the backend (no LLM needed). */
export default function Overview({ onAsk }: { onAsk: (q: string) => void }) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [metric, setMetric] = useState<"churn" | "new" | "expansion" | "contraction">("churn");

  useEffect(() => {
    fetch("/api/overview")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch(() => setErr("Cannot reach the backend on port 8000. Start it with: uvicorn app:app --port 8000"));
  }, []);

  if (err) return <div className="card error" role="alert">{err}</div>;
  if (!data) return <div className="card muted">Loading portfolio…</div>;

  const k = data.kpis;
  const trend = data.months.map((m, i) => ({ month: m, mrr: data.mrr_series[i] }));
  const first = data.mrr_series[0], last = data.mrr_series[data.mrr_series.length - 1];
  const growth = first ? ((last - first) / first) * 100 : 0;
  const total = Object.values(data.status_counts).reduce((a, b) => a + b, 0) || 1;
  const moveData = data.movements.map((m) => ({ month: m.month, value: m[metric] }));
  const MOVE_COLOR = { churn: "var(--bad)", new: "var(--good)", expansion: "var(--accent)", contraction: "var(--warn)" }[metric];

  return (
    <div className="stack">
      <div className="hero">
        <div>
          <div className="eyebrow">Annual run rate · as of {data.reference_date}</div>
          <div className="hero-num">{usd(k.arr)}</div>
          <div className={growth >= 0 ? "delta up" : "delta down"}>
            {growth >= 0 ? "▲" : "▼"} {Math.abs(growth).toFixed(1)}% MRR over 12 months
          </div>
        </div>
        <div className="hero-stats">
          <div><span>MRR</span><b>{usd(k.mrr)}</b></div>
          <div><span>Licenses</span><b>{k.licenses.toLocaleString()}</b></div>
          <div><span>Blended $/license</span><b>{usd(k.blended_cost_per_license)}</b></div>
          <div><span>Paused (idle spend)</span><b>{usd(k.paused_mrr)}</b></div>
        </div>
      </div>

      <div className="status-bar" aria-label="Subscription status mix">
        {Object.entries(data.status_counts).map(([s, n]) => (
          <div key={s} className={`seg seg-${s}`} style={{ flex: n / total }} title={`${s}: ${n}`}>
            {s} · {n}
          </div>
        ))}
      </div>

      <div className="grid2">
        <div className="card">
          <h3>MRR trend · 12 months</h3>
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <AreaChart data={trend}>
                <defs>
                  <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="month" stroke="var(--muted)" fontSize={11} tickLine={false} />
                <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} tickFormatter={compact} width={56} />
                <Tooltip formatter={(v: number) => usd(v)} />
                <Area dataKey="mrr" stroke="var(--accent)" strokeWidth={2} fill="url(#g)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="row">
            <h3>Monthly movements</h3>
            <div className="seg-ctl" role="tablist">
              {(["churn", "new", "expansion", "contraction"] as const).map((m) => (
                <button key={m} role="tab" aria-selected={metric === m} className={metric === m ? "on" : ""} onClick={() => setMetric(m)}>
                  {m}
                </button>
              ))}
            </div>
          </div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={moveData}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="month" stroke="var(--muted)" fontSize={11} tickLine={false} />
                <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} tickFormatter={compact} width={56} />
                <Tooltip formatter={(v: number) => usd(v)} />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Bar dataKey="value" fill={MOVE_COLOR} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h3>Cost per license by department <span className="muted small">vs blended {usd(k.blended_cost_per_license)}</span></h3>
          <div className="dept-list">
            {[...data.by_department].sort((a, b) => b.cost_per_license - a.cost_per_license).map((d) => {
              const max = Math.max(...data.by_department.map((x) => x.cost_per_license)) || 1;
              const over = d.vs_blended_pct > 0;
              return (
                <button key={d.department} className="dept" onClick={() => onAsk(`Why is ${d.department} cost per license ${over ? "above" : "below"} the company average? Break it down by software.`)}
                  title="Click to investigate with Code Mode">
                  <span className="dept-name">{d.department}</span>
                  <span className="dept-bar"><i style={{ width: `${(d.cost_per_license / max) * 100}%`, background: over ? "var(--warn)" : "var(--good)" }} /></span>
                  <span className="dept-val">{usd(d.cost_per_license)}</span>
                  <span className={over ? "pct bad" : "pct good"}>{over ? "+" : ""}{d.vs_blended_pct}%</span>
                </button>
              );
            })}
          </div>
          <p className="muted small">Click a department to investigate it with Code Mode.</p>
        </div>

        <div className="card">
          <h3>Renewals in the next 90 days</h3>
          {data.renewals_90d.length === 0 ? (
            <p className="muted">No active renewals in the next 90 days.</p>
          ) : (
            <ul className="renewals">
              {data.renewals_90d.map((r) => (
                <li key={r.subscription_id}>
                  <span className="date">{r.renewal_date.slice(5)}</span>
                  <span><b>{r.software_name}</b> <span className="muted small">{r.department}</span></span>
                  <span className="num">{usd(r.monthly_cost_usd)}/mo</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
