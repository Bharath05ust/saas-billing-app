"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import type { Subscription } from "@/lib/types";
import { formatValue } from "@/lib/format";

type SortKey = "software_name" | "department" | "monthly_cost_usd" | "active_licenses" | "cpl" | "renewal_date" | "status";
const usd = (n: number) => formatValue(n, "usd");
const cpl = (s: Subscription) => (s.active_licenses ? s.monthly_cost_usd / s.active_licenses : 0);

function csvEscape(v: string | number | null) {
  const s = v === null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Filterable, sortable subscription table with per-row cost history and CSV export. */
export default function Explorer() {
  const [rows, setRows] = useState<Subscription[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("all");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "monthly_cost_usd", dir: -1 });
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/subscriptions")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setRows(d.items))
      .catch(() => setErr("Cannot reach the backend on port 8000."));
  }, []);

  const view = useMemo(() => {
    if (!rows) return [];
    const needle = q.trim().toLowerCase();
    const out = rows.filter(
      (s) =>
        (dept === "all" || s.department === dept) &&
        (status === "all" || s.status === status) &&
        (!needle || s.software_name.toLowerCase().includes(needle) || s.subscription_id.toLowerCase().includes(needle))
    );
    const val = (s: Subscription) => (sort.key === "cpl" ? cpl(s) : s[sort.key]);
    return out.sort((a, b) => {
      const x = val(a), y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [rows, q, dept, status, sort]);

  if (err) return <div className="card error" role="alert">{err}</div>;
  if (!rows) return <div className="card muted">Loading subscriptions…</div>;

  const total = view.filter((s) => s.status === "active").reduce((a, s) => a + s.monthly_cost_usd, 0);
  const depts = Array.from(new Set(rows.map((s) => s.department))).sort();

  const header = (key: SortKey, label: string, num = false) => (
    <th className={num ? "num" : ""} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button className="th-btn" onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))}>
        {label} {sort.key === key ? (sort.dir === 1 ? "↑" : "↓") : ""}
      </button>
    </th>
  );

  const exportCsv = () => {
    const head = ["subscription_id", "software_name", "department", "status", "active_licenses", "monthly_cost_usd", "renewal_date", "start_date", "end_date"];
    const lines = [head.join(",")].concat(
      view.map((s) => head.map((h) => csvEscape(s[h as keyof Subscription] as string | number | null)).join(","))
    );
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "subscriptions.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card">
      <div className="filters">
        <input type="search" placeholder="Search software or ID…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <select value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Department">
          <option value="all">All departments</option>
          {depts.map((d) => <option key={d}>{d}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="all">All statuses</option>
          <option>active</option><option>paused</option><option>cancelled</option>
        </select>
        <span className="muted small grow">{view.length} of {rows.length} · active MRR {usd(total)}</span>
        <button className="ghost" onClick={exportCsv} disabled={!view.length}>Export CSV</button>
      </div>

      {view.length === 0 ? (
        <p className="muted">No subscriptions match these filters.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {header("software_name", "Software")}
                {header("department", "Department")}
                {header("status", "Status")}
                {header("active_licenses", "Licenses", true)}
                {header("monthly_cost_usd", "Monthly", true)}
                {header("cpl", "$/license", true)}
                {header("renewal_date", "Renews")}
              </tr>
            </thead>
            <tbody>
              {view.map((s) => (
                <Fragment key={s.subscription_id}>
                  <tr className="clickable" onClick={() => setOpen(open === s.subscription_id ? null : s.subscription_id)}>
                    <td><b>{s.software_name}</b> <span className="muted small">{s.subscription_id}</span></td>
                    <td>{s.department}</td>
                    <td><span className={`tag tag-${s.status}`}>{s.status}</span></td>
                    <td className="num">{s.active_licenses}</td>
                    <td className="num">{usd(s.monthly_cost_usd)}</td>
                    <td className="num">{usd(cpl(s))}</td>
                    <td>{s.renewal_date}</td>
                  </tr>
                  {open === s.subscription_id && (
                    <tr className="detail">
                      <td colSpan={7}>
                        <div className="history">
                          <span className="muted small">Cost history</span>
                          {s.cost_history.map((h, i) => (
                            <span key={i} className="step">
                              <i>{h.effective_date}</i> {usd(h.monthly_cost_usd)}
                              {i > 0 && (
                                <em className={h.monthly_cost_usd >= s.cost_history[i - 1].monthly_cost_usd ? "good" : "bad"}>
                                  {h.monthly_cost_usd >= s.cost_history[i - 1].monthly_cost_usd ? " expansion" : " contraction"}
                                </em>
                              )}
                            </span>
                          ))}
                          {s.end_date && <span className="step"><i>{s.end_date}</i> billing stopped ({s.status})</span>}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
