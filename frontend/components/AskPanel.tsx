"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import ResultView from "./ResultView";
import ScriptViewer from "./ScriptViewer";
import type { QueryResponse } from "@/lib/types";

const EXAMPLES = [
  "What is our current ARR based on active subscriptions?",
  "Show month-over-month churn and expansion MRR for the last 6 months.",
  "Which departments have the highest cost per license compared to the company average?",
  "Prorate the cost of cancelled and paused subscriptions for Q3 2026.",
  "Which software is duplicated across departments, and what does the overlap cost per month?",
  "Forecast ARR for the next 12 months using the average MoM net change.",
];
const STEPS = ["Writing script", "Validating in sandbox", "Executing"];
const HISTORY_KEY = "finops.history.v1";

interface HistoryItem { id: number; at: number; data: QueryResponse }

function loadHistory(): HistoryItem[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(stored)) return [];
    return stored.filter((item): item is HistoryItem =>
      item !== null &&
      typeof item === "object" &&
      typeof item.id === "number" &&
      typeof item.at === "number" &&
      item.data !== null &&
      typeof item.data === "object" &&
      typeof item.data.ok === "boolean" &&
      typeof item.data.query === "string" &&
      typeof item.data.model === "string" &&
      typeof item.data.script === "string" &&
      Array.isArray(item.data.attempts)
    );
  } catch {
    return [];
  }
}

/** Natural-language -> Code Mode pipeline, with animated progress and a persistent history rail. */
export default function AskPanel({ seed }: { seed: { q: string; n: number } | null }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [data, setData] = useState<QueryResponse | null>(null);
  const [netError, setNetError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const seeded = useRef(-1);
  const pendingSeed = useRef<{ q: string; n: number } | null>(null);

  useEffect(() => setHistory(loadHistory()), []);

  // Elapsed timer + pipeline stepper (stages are indicative; the server does the real work in one call).
  useEffect(() => {
    if (!loading) return;
    const t0 = Date.now();
    setStep(0); setElapsed(0);
    const id = setInterval(() => {
      const s = (Date.now() - t0) / 1000;
      setElapsed(s);
      setStep(s < 6 ? 0 : s < 8 ? 1 : 2);
    }, 200);
    return () => clearInterval(id);
  }, [loading]);

  async function run(q: string) {
    q = q.trim();
    if (q.length < 3 || loading) return;
    setQuery(q); setLoading(true); setNetError(null); setData(null);
    try {
      const res = await fetch("/api/query", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(res.status === 422 ? "Please enter a question (3–2000 characters)." : `Server error ${res.status}: ${body.slice(0, 200)}`);
      }
      const d = (await res.json()) as QueryResponse;
      setData(d);
      const next = [{ id: Date.now(), at: Date.now(), data: d }, ...history].slice(0, 12);
      setHistory(next);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* storage full/unavailable */ }
    } catch (err) {
      setNetError(err instanceof Error ? err.message : "Request failed. Is the backend running on port 8000?");
    } finally {
      setLoading(false);
    }
  }

  // Questions launched from other tabs (e.g. clicking a department on the Overview).
  useEffect(() => {
    if (seed && seed.n !== seeded.current) {
      seeded.current = seed.n;
      if (loading) pendingSeed.current = seed;
      else run(seed.q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, loading]);

  useEffect(() => {
    if (loading || !pendingSeed.current) return;
    const pending = pendingSeed.current;
    pendingSeed.current = null;
    run(pending.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  const clearHistory = () => { setHistory([]); try { localStorage.removeItem(HISTORY_KEY); } catch { /* ignore */ } };

  return (
    <div className="ask-layout">
      <div className="stack">
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); run(query); }}>
          <textarea
            value={query} onChange={(e) => setQuery(e.target.value)} rows={3} maxLength={2000}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(query); }}
            placeholder="Ask anything: “Calculate MoM churn and forecast ARR for the next 12 months”"
            aria-label="FinOps question"
          />
          <div className="row">
            <span className="muted small">Ctrl/⌘ + Enter to run · {query.length}/2000</span>
            <button className="primary" type="submit" disabled={loading || query.trim().length < 3}>
              {loading ? "Running…" : "Run in Code Mode"}
            </button>
          </div>
          <div className="chips">
            {EXAMPLES.map((ex) => (
              <button type="button" key={ex} className="chip" disabled={loading} onClick={() => run(ex)}>{ex}</button>
            ))}
          </div>
        </form>

        {loading && (
          <div className="card" role="status" aria-live="polite">
            <div className="row">
              <span className="loading-title"><span className="spinner" aria-hidden /> <strong>Code Mode Engine Executing...</strong></span>
              <span className="muted small">{elapsed.toFixed(1)}s</span>
            </div>
            <ol className="steps">
              {STEPS.map((s, i) => (
                <li key={s} className={i < step ? "done" : i === step ? "now" : ""}>{s}</li>
              ))}
            </ol>
          </div>
        )}

        {netError && <div className="card error" role="alert">{netError}</div>}

        {data && !loading && (
          <>
            {data.ok && data.result ? (
              <ResultView result={data.result} />
            ) : (
              <div className="card error" role="alert">
                <h3>Execution failed</h3>
                <p>{data.error?.type}: {data.error?.message}</p>
                <p className="muted small">Open “View Generated Script” to inspect what was run.</p>
              </div>
            )}
            <ScriptViewer data={data} />
          </>
        )}

        {!data && !loading && !netError && (
          <div className="card empty">
            <h3>How Code Mode works</h3>
            <p className="muted">Your question becomes a Python script, which runs in an isolated sandbox against the billing data. Only the computed JSON comes back, so every number is calculated, never guessed.</p>
          </div>
        )}
      </div>

      <aside className="card history">
        <div className="row">
          <h3>History</h3>
          {history.length > 0 && <button className="ghost" onClick={clearHistory}>Clear</button>}
        </div>
        {history.length === 0 ? <p className="muted small">Your past questions appear here.</p> : (
          <ul>
            {history.map((h) => (
              <li key={h.id}>
                <button onClick={() => { setData(h.data); setQuery(h.data.query); setNetError(null); }}>
                  <span className={h.data.ok ? "dot ok" : "dot bad"} aria-label={h.data.ok ? "succeeded" : "failed"} />
                  <span className="hq">{h.data.query}</span>
                  <span className="muted small">{new Date(h.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
