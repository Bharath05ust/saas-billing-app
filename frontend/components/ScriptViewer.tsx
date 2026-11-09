"use client";

import { useState } from "react";
import type { QueryResponse } from "@/lib/types";

/** Toggle that reveals the exact script the LLM wrote (and any failed attempts). */
export default function ScriptViewer({ data }: { data: QueryResponse }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  if (!data.script) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(data.script);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: ignore */
    }
  };

  return (
    <div className="card">
      <div className="row">
        <label className="toggle">
          <input type="checkbox" checked={open} onChange={(e) => setOpen(e.target.checked)} />
          <span>View Generated Script</span>
        </label>
        <span className="muted small">
          {data.attempts.length} attempt{data.attempts.length === 1 ? "" : "s"} · {data.model} · {data.duration_ms} ms
        </span>
      </div>
      {open && (
        <div className="stack">
          {data.attempts.map((a, i) => (
            <div key={i}>
              <div className="row">
                <strong>
                  Attempt {i + 1} {a.ok ? "✓ succeeded" : "✗ failed"}
                </strong>
                {i === data.attempts.length - 1 && (
                  <button className="ghost" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
                )}
              </div>
              {a.error && <p className="error-inline">{a.error.type}: {a.error.message}</p>}
              <pre className="code"><code>{a.script}</code></pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
