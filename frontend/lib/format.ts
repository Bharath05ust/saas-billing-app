import type { Unit } from "./types";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const num = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatValue(value: number | string | null | undefined, unit?: Unit): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (!Number.isFinite(value)) return "—";
  switch (unit) {
    case "usd":
      return usd.format(value);
    case "percent":
      return `${num.format(value)}%`;
    default:
      return num.format(value);
  }
}

/** Heuristic for table cells: money-looking columns get currency formatting. */
export function formatCell(cell: string | number | null, column: string): string {
  if (typeof cell !== "number") return cell === null ? "—" : String(cell);
  const c = column.toLowerCase();
  if (/(count|^#)/.test(c) || /^(active )?licenses?$/.test(c)) return num.format(cell);
  if (/(%|percent|pct|rate)/.test(c) && !/run rate/.test(c)) return `${num.format(cell)}%`;
  if (/(per license|usd|cost|spend|mrr|arr|revenue|price|saving|\$)/.test(c)) return usd.format(cell);
  return num.format(cell);
}
