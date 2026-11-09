"""
app.py - Backend Orchestrator (FastAPI).

POST /api/query   {"query": "..."}  ->  generated script + sandbox JSON result

Flow: question -> LLM writes a Python script (system prompt in prompts.py) ->
Code Mode Engine runs it in the sandbox -> stdout JSON returned to the UI.
If the script fails, the error is fed back to the LLM for up to MAX_ATTEMPTS-1
automatic repairs (security violations included - the model learns the rules).

Run:  uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import datetime
import logging
import os
import time
from pathlib import Path

import openai
import sandbox_sdk
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field

from engine import extract_code, run_script
from prompts import SYSTEM_PROMPT, build_repair_message

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("code_mode")

load_dotenv(Path(__file__).with_name(".env"))
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
API_BASE_URL = "https://api.groq.com/openai/v1"
MAX_ATTEMPTS = int(os.getenv("CODE_MODE_MAX_ATTEMPTS", "2"))
if MAX_ATTEMPTS < 1:
    raise ValueError("CODE_MODE_MAX_ATTEMPTS must be at least 1.")
MAX_QUERY_CHARS = 2000

app = FastAPI(title="SaaS Billing Code Mode API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_client: OpenAI | None = None
_client_api_key: str | None = None


class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=MAX_QUERY_CHARS)


class LLMError(Exception):
    pass


def generate_script(messages: list[dict]) -> str:
    """Ask the LLM for a script. Raises LLMError with a user-safe message."""
    global _client, _client_api_key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set on the server. Overview and Explorer still work without it.")

    if _client is None or _client_api_key != api_key:
        _client = OpenAI(api_key=api_key, base_url=API_BASE_URL)
        _client_api_key = api_key

    try:
        resp = _client.chat.completions.create(
            model=MODEL,
            max_tokens=16000,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        )
    except openai.AuthenticationError:
        raise LLMError("The Groq API key is missing or invalid.")
    except openai.RateLimitError:
        raise LLMError("The model is rate limited right now; retry in a moment.")
    except openai.APIConnectionError:
        raise LLMError("Could not reach the Groq API.")
    except openai.APIStatusError as exc:
        log.warning("Groq API request failed: status=%s model=%s", exc.status_code, MODEL)
        if exc.status_code == 402:
            raise LLMError(
                "Groq returned 402 Payment Required. Check your Groq account billing and usage limits."
            )
        if exc.status_code == 404:
            raise LLMError(
                f"The selected Groq model is unavailable: {MODEL}. Check the model ID in GroqCloud."
            )
        raise LLMError(f"Groq API error ({exc.status_code}). Check model availability, API key, and quota.")

    if not resp.choices:
        raise LLMError("The Groq model returned no response choices.")
    choice = resp.choices[0]
    if choice.finish_reason == "content_filter":
        raise LLMError("The model declined to answer this request.")
    if choice.finish_reason == "length":
        raise LLMError("The generated script was cut off (too long). Try a narrower question.")

    text = choice.message.content
    if not text or not text.strip():
        raise LLMError("The model returned an empty response.")
    return text


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL}


@app.get("/api/subscriptions")
def subscriptions() -> dict:
    """Raw dataset for the Explorer tab (no LLM involved)."""
    return {"reference_date": sandbox_sdk.get_reference_date(), "items": sandbox_sdk.get_subscriptions()}


@app.get("/api/overview")
def overview() -> dict:
    """Deterministic portfolio snapshot for the Overview tab (no LLM involved)."""
    ref = datetime.date.fromisoformat(sandbox_sdk.get_reference_date())
    subs = sandbox_sdk.get_subscriptions()
    div = sandbox_sdk.safe_divide

    def month_end(m: str) -> str:
        y, mo = int(m[:4]), int(m[5:])
        nxt = datetime.date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
        return min(nxt - datetime.timedelta(days=1), ref).isoformat()

    months = sandbox_sdk.last_n_months(12)
    ends = [month_end(m) for m in months]
    mrr_series = [round(sum(sandbox_sdk.mrr_at(s, e) for s in subs), 2) for e in ends]

    # Movements per month: new / expansion / contraction / churn (vs previous month end).
    movements = []
    for i in range(1, len(months)):
        new = exp = con = churn = 0.0
        for s in subs:
            a, b = sandbox_sdk.mrr_at(s, ends[i - 1]), sandbox_sdk.mrr_at(s, ends[i])
            if a == 0 and b > 0:
                new += b
            elif a > 0 and b == 0:
                churn += a
            elif a > 0 and b > a:
                exp += b - a
            elif a > 0 and b < a:
                con += a - b
        prev = mrr_series[i - 1]
        movements.append({
            "month": months[i], "new": round(new, 2), "expansion": round(exp, 2),
            "contraction": round(con, 2), "churn": round(churn, 2),
            "churn_pct": round(div(churn, prev) * 100, 2),
        })

    active = [s for s in subs if s["status"] == "active"]
    mrr = sum(s["monthly_cost_usd"] for s in active)
    licenses = sum(s["active_licenses"] for s in active)
    blended = div(mrr, licenses)

    by_dept = []
    for d in sandbox_sdk.DEPARTMENTS:
        ds = [s for s in active if s["department"] == d]
        cost, lic = sum(s["monthly_cost_usd"] for s in ds), sum(s["active_licenses"] for s in ds)
        cpl = div(cost, lic)
        by_dept.append({"department": d, "mrr": round(cost, 2), "licenses": lic, "subscriptions": len(ds),
                        "cost_per_license": round(cpl, 2),
                        "vs_blended_pct": round((div(cpl, blended) - 1) * 100, 1) if blended else 0})

    horizon = ref + datetime.timedelta(days=90)
    renewals = sorted(
        ({"subscription_id": s["subscription_id"], "software_name": s["software_name"], "department": s["department"],
          "renewal_date": s["renewal_date"], "monthly_cost_usd": s["monthly_cost_usd"]}
         for s in active if ref <= datetime.date.fromisoformat(s["renewal_date"]) <= horizon),
        key=lambda r: r["renewal_date"])

    return {
        "reference_date": ref.isoformat(),
        "kpis": {"mrr": round(mrr, 2), "arr": round(mrr * 12, 2), "licenses": licenses,
                 "blended_cost_per_license": round(blended, 2),
                 "paused_mrr": round(sum(s["monthly_cost_usd"] for s in subs if s["status"] == "paused"), 2),
                 "cancelled_mrr": round(sum(s["monthly_cost_usd"] for s in subs if s["status"] == "cancelled"), 2)},
        "status_counts": {st: sum(1 for s in subs if s["status"] == st) for st in sandbox_sdk.STATUSES},
        "months": months, "mrr_series": mrr_series, "movements": movements,
        "by_department": by_dept, "renewals_90d": renewals,
    }


@app.post("/api/query")
def query(req: QueryRequest) -> dict:
    started = time.perf_counter()
    question = req.query.strip()
    messages: list[dict] = [{"role": "user", "content": question}]
    attempts: list[dict] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = generate_script(messages)
        except LLMError as exc:
            return _response(False, question, attempts, started, error={"type": "LLMError", "message": str(exc)})

        script = extract_code(raw)
        outcome = run_script(script)
        log.info("attempt=%d ok=%s err=%s ms=%d", attempt, outcome.ok, outcome.error_type, outcome.duration_ms)
        attempts.append({
            "script": script,
            "ok": outcome.ok,
            "error": None if outcome.ok else {"type": outcome.error_type, "message": outcome.error_message},
            "duration_ms": outcome.duration_ms,
        })

        if outcome.ok:
            return _response(True, question, attempts, started, result=outcome.result)

        # Feed the failure back so the model can repair its own script.
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": build_repair_message(outcome.error_type or "Error", outcome.error_message or "")},
        ]

    last = attempts[-1]["error"]
    return _response(False, question, attempts, started, error=last)


def _response(ok, question, attempts, started, result=None, error=None) -> dict:
    return {
        "ok": ok,
        "query": question,
        "model": MODEL,
        "script": attempts[-1]["script"] if attempts else "",
        "attempts": attempts,
        "result": result,
        "error": error,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
