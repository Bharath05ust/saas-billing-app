/** Mirrors the OUTPUT JSON CONTRACT in backend/prompts.py. All keys optional: the UI degrades gracefully. */
export type Unit = "usd" | "percent" | "count" | "text";

export interface Kpi {
  label: string;
  value: number | string;
  unit?: Unit;
}

export interface ChartSpec {
  type: "bar" | "line" | "pie";
  x_label?: string;
  y_label?: string;
  labels: string[];
  series: { name: string; data: number[] }[];
}

export interface TableSpec {
  columns: string[];
  rows: (string | number | null)[][];
}

export interface CodeModeResult {
  title?: string;
  summary?: string;
  total?: number;
  kpis?: Kpi[];
  chart?: ChartSpec | null;
  table?: TableSpec | null;
  assumptions?: string[];
  [key: string]: unknown;
}

export interface Attempt {
  script: string;
  ok: boolean;
  error: { type: string; message: string } | null;
  duration_ms: number;
}

export interface QueryResponse {
  ok: boolean;
  query: string;
  model: string;
  script: string;
  attempts: Attempt[];
  result: CodeModeResult | null;
  error: { type: string; message: string } | null;
  duration_ms: number;
}

export interface Subscription {
  subscription_id: string;
  software_name: string;
  department: string;
  monthly_cost_usd: number;
  status: "active" | "cancelled" | "paused";
  active_licenses: number;
  renewal_date: string;
  start_date: string;
  end_date: string | null;
  cost_history: { effective_date: string; monthly_cost_usd: number }[];
}

export interface Overview {
  reference_date: string;
  kpis: {
    mrr: number; arr: number; licenses: number; blended_cost_per_license: number;
    paused_mrr: number; cancelled_mrr: number;
  };
  status_counts: Record<string, number>;
  months: string[];
  mrr_series: number[];
  movements: { month: string; new: number; expansion: number; contraction: number; churn: number; churn_pct: number }[];
  by_department: {
    department: string; mrr: number; licenses: number; subscriptions: number;
    cost_per_license: number; vs_blended_pct: number;
  }[];
  renewals_90d: { subscription_id: string; software_name: string; department: string; renewal_date: string; monthly_cost_usd: number }[];
}
