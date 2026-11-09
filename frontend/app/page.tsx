"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import AskPanel from "@/components/AskPanel";
import Explorer from "@/components/Explorer";
import Overview from "@/components/Overview";

type Tab = "overview" | "ask" | "explorer";
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "◧" },
  { id: "ask", label: "Ask Code Mode", icon: "⌘" },
  { id: "explorer", label: "Explorer", icon: "☰" },
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("overview");
  const [seed, setSeed] = useState<{ q: string; n: number } | null>(null);
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  const [health, setHealth] = useState<"up" | "down" | "?">("?");

  // Theme: remembered choice, else the OS preference.
  useEffect(() => {
    let t: "light" | "dark" = "light";
    try { const s = localStorage.getItem("finops.theme"); if (s === "light" || s === "dark") t = s; } catch { /* ignore */ }
    setTheme(t);
  }, []);
  useEffect(() => {
    if (!theme) return;
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("finops.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    fetch("/api/health").then((r) => setHealth(r.ok ? "up" : "down")).catch(() => setHealth("down"));
  }, []);

  const ask = (q: string) => { setSeed({ q, n: Date.now() }); setTab("ask"); };

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">
          <Image
            className="logo-image"
            src="/ust-logo.png"
            alt="UST logo"
            width={57}
            height={38}
          />
          <span>UST<small>Financial Insights</small></span>
        </div>
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "nav on" : "nav"} aria-current={tab === t.id ? "page" : undefined} onClick={() => setTab(t.id)}>
            <span aria-hidden>{t.icon}</span>{t.label}
          </button>
        ))}
        <div className="rail-foot">
          <span className={`health ${health}`}>{health === "up" ? "Backend online" : health === "down" ? "Backend offline" : "Checking…"}</span>
          <button className="ghost" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle theme">
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </nav>

      <main>
        <header>
          <h1>{TABS.find((t) => t.id === tab)?.label}</h1>
          <p className="muted">
            {tab === "overview" && "Portfolio metrics computed from the configured subscription data."}
            {tab === "ask" && "Ask complex financial questions. Code Mode writes and safely runs an analysis script, then explains the computed results."}
            {tab === "explorer" && "Browse, filter and export every subscription. Click a row for its cost history."}
          </p>
        </header>
        {/* Keep Ask mounted so an in-flight query survives tab switches. */}
        <div hidden={tab !== "overview"}><Overview onAsk={ask} /></div>
        <div hidden={tab !== "ask"}><AskPanel seed={seed} /></div>
        {tab === "explorer" && <Explorer />}
      </main>
    </div>
  );
}
