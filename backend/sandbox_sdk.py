"""
sandbox_sdk.py - the ONLY door between LLM-written scripts and the SaaS billing data.

Design rules
------------
* Read-only: every query returns deep copies; scripts can never mutate the store.
* Stdlib only (no network, no file I/O at query time). The dataset is generated
  deterministically in-process, so results are reproducible across runs.
* Everything not meant for scripts is underscore-prefixed. The sandbox runner's
  AST validator rejects any attribute access starting with "_", so scripts can
  only reach the names listed in __all__.

Data schema (per subscription)
------------------------------
Base schema (as specified):
    subscription_id   str
    software_name     str
    department        Engineering | Sales | Marketing | HR | Finance | Operations
    monthly_cost_usd  float   current contract cost per month
    status            active | cancelled | paused
    active_licenses   int
    renewal_date      YYYY-MM-DD

Extensions (needed so MoM churn / expansion / proration are computable -
a pure snapshot cannot express them):
    start_date        YYYY-MM-DD  first billing day
    end_date          YYYY-MM-DD | None   day billing stopped (cancelled or paused)
    cost_history      list[{"effective_date", "monthly_cost_usd"}]  ascending; first
                      entry is the start cost, later entries are upsells/downsells
"""

from __future__ import annotations

import copy as _copy
import datetime as _dt
import random as _random

__all__ = [
    "DEPARTMENTS",
    "STATUSES",
    "get_subscriptions",
    "get_reference_date",
    "last_n_months",
    "month_range",
    "mrr_at",
    "prorated_cost",
    "safe_divide",
]

DEPARTMENTS = ["Engineering", "Sales", "Marketing", "HR", "Finance", "Operations"]
STATUSES = ["active", "cancelled", "paused"]

# "Today" for the mock dataset. Scripts must use this instead of the wall clock
# so answers are deterministic and consistent with the data.
_REFERENCE_DATE = _dt.date(2026, 11, 6)

# (software, department, list price per license per month USD)
_CATALOG = [
    ("GitHub Enterprise", "Engineering", 21.0),
    ("Datadog", "Engineering", 31.0),
    ("Jira", "Engineering", 8.15),
    ("JetBrains All Products", "Engineering", 24.9),
    ("Snyk", "Engineering", 52.0),
    ("PagerDuty", "Engineering", 29.0),
    ("Slack", "Engineering", 8.75),
    ("Salesforce", "Sales", 165.0),
    ("Gong", "Sales", 110.0),
    ("Outreach", "Sales", 100.0),
    ("ZoomInfo", "Sales", 90.0),
    ("LinkedIn Sales Navigator", "Sales", 99.0),
    ("Slack", "Sales", 8.75),
    ("HubSpot", "Marketing", 90.0),
    ("Canva Teams", "Marketing", 10.0),
    ("Figma", "Marketing", 15.0),
    ("Semrush", "Marketing", 120.0),
    ("Adobe Creative Cloud", "Marketing", 55.0),
    ("Asana", "Marketing", 11.0),
    ("Workday", "HR", 45.0),
    ("Lattice", "HR", 11.0),
    ("Greenhouse", "HR", 30.0),
    ("BambooHR", "HR", 9.0),
    ("Zoom", "HR", 15.0),
    ("NetSuite", "Finance", 129.0),
    ("Expensify", "Finance", 9.0),
    ("Bill.com", "Finance", 45.0),
    ("Coupa", "Finance", 70.0),
    ("Slack", "Finance", 8.75),
    ("ServiceNow", "Operations", 100.0),
    ("Asana", "Operations", 11.0),
    ("Zoom", "Operations", 15.0),
    ("Monday.com", "Operations", 12.0),
    ("Smartsheet", "Operations", 9.0),
    ("Slack", "Operations", 8.75),
    ("Figma", "Engineering", 15.0),
]


def _iso(d: _dt.date) -> str:
    return d.isoformat()


def _next_anniversary(start: _dt.date, ref: _dt.date) -> _dt.date:
    """First anniversary of `start` that falls on/after `ref` (handles Feb 29)."""
    year = ref.year
    while True:
        try:
            cand = start.replace(year=year)
        except ValueError:  # Feb 29 on a non-leap year
            cand = start.replace(year=year, day=28)
        if cand >= ref:
            return cand
        year += 1


def _build_dataset() -> list[dict]:
    rng = _random.Random(20261106)  # fixed seed -> reproducible data
    rows: list[dict] = []
    for idx, (name, dept, unit) in enumerate(_CATALOG, start=1):
        big = unit >= 90
        licenses0 = rng.randint(8, 45) if big else rng.randint(15, 140)
        start = _REFERENCE_DATE - _dt.timedelta(days=rng.randint(60, 900))
        history = [{"effective_date": _iso(start), "licenses": licenses0}]

        # ~45% of subscriptions had one expansion/contraction event.
        if rng.random() < 0.45:
            span = (_REFERENCE_DATE - start).days - 40
            if span > 20:
                change = start + _dt.timedelta(days=rng.randint(30, 30 + span - 10))
                factor = rng.choice([1.15, 1.3, 1.5, 0.85])
                history.append(
                    {
                        "effective_date": _iso(change),
                        "licenses": max(1, round(licenses0 * factor)),
                    }
                )

        status = rng.choices(STATUSES, weights=[72, 18, 10])[0]
        end_date = None
        if status != "active":
            last_eff = _dt.date.fromisoformat(history[-1]["effective_date"])
            earliest = last_eff + _dt.timedelta(days=14)
            latest = _REFERENCE_DATE - _dt.timedelta(days=3)
            if earliest <= latest:
                end_date = earliest + _dt.timedelta(days=rng.randint(0, (latest - earliest).days))
            else:  # not enough runway: keep it active so data stays consistent
                status = "active"

        cost_history = [
            {
                "effective_date": h["effective_date"],
                "monthly_cost_usd": round(h["licenses"] * unit, 2),
            }
            for h in history
        ]
        rows.append(
            {
                "subscription_id": f"SUB-{idx:04d}",
                "software_name": name,
                "department": dept,
                "monthly_cost_usd": cost_history[-1]["monthly_cost_usd"],
                "status": status,
                "active_licenses": history[-1]["licenses"],
                "renewal_date": _iso(_next_anniversary(start, _REFERENCE_DATE)),
                "start_date": _iso(start),
                "end_date": _iso(end_date) if end_date else None,
                "cost_history": cost_history,
            }
        )
    return rows


_DATA: list[dict] = _build_dataset()


# --------------------------------------------------------------------------- #
# Public API (the only names scripts can use)
# --------------------------------------------------------------------------- #
def get_subscriptions(department=None, status=None, software_name=None) -> list[dict]:
    """Return deep copies of subscriptions, optionally filtered (AND semantics).

    Raises ValueError on an unknown department/status so typos fail loudly instead
    of silently returning an empty (and misleading) result.
    """
    if department is not None and department not in DEPARTMENTS:
        raise ValueError(f"Unknown department {department!r}; valid: {DEPARTMENTS}")
    if status is not None and status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}; valid: {STATUSES}")
    out = []
    for row in _DATA:
        if department is not None and row["department"] != department:
            continue
        if status is not None and row["status"] != status:
            continue
        if software_name is not None and row["software_name"].lower() != str(software_name).lower():
            continue
        out.append(_copy.deepcopy(row))
    return out


def get_reference_date() -> str:
    """The dataset's 'today' as YYYY-MM-DD. Use this, never the wall clock."""
    return _iso(_REFERENCE_DATE)


def safe_divide(numerator, denominator, default=0.0):
    """numerator / denominator, or `default` when denominator is 0/None."""
    try:
        if not denominator:
            return default
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return default


def _parse_month(m: str) -> tuple[int, int]:
    y, mo = str(m).split("-")
    y, mo = int(y), int(mo)
    if not 1 <= mo <= 12:
        raise ValueError(f"Bad month {m!r}; expected YYYY-MM")
    return y, mo


def month_range(start_month: str, end_month: str) -> list[str]:
    """Inclusive list of 'YYYY-MM' strings from start_month to end_month."""
    y, m = _parse_month(start_month)
    ey, em = _parse_month(end_month)
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def last_n_months(n: int) -> list[str]:
    """The last n calendar months ending at the reference month, oldest first."""
    n = int(n)
    if n <= 0:
        return []
    y, m = _REFERENCE_DATE.year, _REFERENCE_DATE.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def mrr_at(sub: dict, as_of: str) -> float:
    """Monthly recurring cost of `sub` on date `as_of` (YYYY-MM-DD).

    0.0 before start_date and on/after end_date (cancelled or paused).
    Otherwise the latest cost_history entry effective on/before `as_of`.
    """
    d = _dt.date.fromisoformat(as_of)
    if d < _dt.date.fromisoformat(sub["start_date"]):
        return 0.0
    if sub.get("end_date") and d >= _dt.date.fromisoformat(sub["end_date"]):
        return 0.0
    cost = 0.0
    for entry in sub["cost_history"]:
        if _dt.date.fromisoformat(entry["effective_date"]) <= d:
            cost = entry["monthly_cost_usd"]
        else:
            break
    return float(cost)


def prorated_cost(sub: dict, period_start: str, period_end: str) -> float:
    """Actual billed cost for `sub` over [period_start, period_end] inclusive.

    Day-based proration: each billable day costs mrr_at(day) * 12 / 365, so
    mid-period cancellations/pauses and mid-period upsells are handled exactly.
    Periods are capped at 10 years to bound runtime.
    """
    start = _dt.date.fromisoformat(period_start)
    end = _dt.date.fromisoformat(period_end)
    if end < start:
        return 0.0
    days = min((end - start).days + 1, 3660)
    total = 0.0
    for i in range(days):
        day = start + _dt.timedelta(days=i)
        total += mrr_at(sub, _iso(day)) * 12.0 / 365.0
    return round(total, 2)
