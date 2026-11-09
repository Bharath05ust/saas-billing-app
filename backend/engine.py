"""
engine.py - the Code Mode Engine: runs a generated script in an isolated subprocess
and turns every possible outcome (success, timeout, crash, bad output) into a
structured EngineResult. It never raises for script problems.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

RUNNER = Path(__file__).with_name("sandbox_runner.py")
TIMEOUT_SECONDS = float(os.getenv("CODE_MODE_TIMEOUT", "15"))
MAX_STDOUT_BYTES = 1_000_000
if not math.isfinite(TIMEOUT_SECONDS) or TIMEOUT_SECONDS <= 0:
    raise ValueError("CODE_MODE_TIMEOUT must be a positive, finite number of seconds.")

_FENCE = re.compile(r"^```[a-zA-Z0-9]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


@dataclass
class EngineResult:
    ok: bool
    result: dict | None = None
    error_type: str | None = None
    error_message: str | None = None
    stdout: str = ""
    duration_ms: int = 0
    extra: dict = field(default_factory=dict)


def extract_code(llm_text: str) -> str:
    """The model is told to emit raw code; strip a markdown fence if it adds one anyway."""
    text = llm_text.strip()
    m = _FENCE.match(text)
    if m:
        return m.group(1).strip()
    if "```" in text:  # prose + fenced block: take the first fenced block
        blocks = re.findall(r"```[a-zA-Z0-9]*\s*\n(.*?)```", text, re.DOTALL)
        if blocks:
            return blocks[0].strip()
    return text


def _scrub(value):
    """Reject NaN/Infinity (invalid JSON for browsers) by raising ValueError."""
    raise ValueError(f"non-finite number {value} in output")


def _result_error(result: object) -> str | None:
    """Check the optional output sections before the UI attempts to render them."""
    if not isinstance(result, dict):
        return "The script must print a JSON object."

    for key in ("title", "summary"):
        if key in result and not isinstance(result[key], str):
            return f"'{key}' must be a string."
    if "total" in result and (
        isinstance(result["total"], bool) or not isinstance(result["total"], (int, float))
    ):
        return "'total' must be a number."

    if "kpis" in result:
        kpis = result["kpis"]
        if not isinstance(kpis, list):
            return "'kpis' must be a list."
        for item in kpis:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                return "Each KPI must be an object with a string 'label'."
            value = item.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                return "Each KPI 'value' must be a number or string."
            if "unit" in item and item["unit"] not in ("usd", "percent", "count", "text"):
                return "KPI 'unit' must be usd, percent, count, or text."

    if "chart" in result and result["chart"] is not None:
        chart = result["chart"]
        if not isinstance(chart, dict) or chart.get("type") not in ("bar", "line", "pie"):
            return "'chart' must be null or a supported chart object."
        labels, series = chart.get("labels"), chart.get("series")
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            return "Chart 'labels' must be a list of strings."
        if not isinstance(series, list):
            return "Chart 'series' must be a list."
        for item in series:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("data"), list)
                or len(item["data"]) != len(labels)
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in item["data"])
            ):
                return "Each chart series needs a string name and numeric data matching the labels."
        for key in ("x_label", "y_label"):
            if key in chart and not isinstance(chart[key], str):
                return f"Chart '{key}' must be a string."

    if "table" in result and result["table"] is not None:
        table = result["table"]
        if not isinstance(table, dict):
            return "'table' must be null or a table object."
        columns, rows = table.get("columns"), table.get("rows")
        if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
            return "Table 'columns' must be a list of strings."
        if not isinstance(rows, list):
            return "Table 'rows' must be a list."
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != len(columns)
                or any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float, str)))
                       for value in row)
            ):
                return "Each table row must contain one string, number, or null value per column."

    if "assumptions" in result and (
        not isinstance(result["assumptions"], list)
        or not all(isinstance(item, str) for item in result["assumptions"])
    ):
        return "'assumptions' must be a list of strings."
    return None


def run_script(script: str) -> EngineResult:
    start = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - start) * 1000)

    # Minimal environment: no API keys / secrets are visible to generated code.
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")

    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(RUNNER)],
            input=script.encode("utf-8"),
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
            cwd=str(RUNNER.parent),
        )
    except subprocess.TimeoutExpired:
        return EngineResult(False, error_type="Timeout",
                            error_message=f"Script exceeded {TIMEOUT_SECONDS:g}s and was killed.",
                            duration_ms=elapsed())
    except OSError as exc:
        return EngineResult(False, error_type="EngineFailure",
                            error_message=f"Could not start sandbox: {exc}", duration_ms=elapsed())

    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        etype, emsg = "RuntimeError", stderr[-1000:] or f"exit code {proc.returncode}"
        try:  # runner reports a JSON line on stderr
            payload = json.loads(stderr.splitlines()[-1])
            etype, emsg = payload["type"], payload["message"]
        except (ValueError, KeyError, IndexError):
            pass
        return EngineResult(False, error_type=etype, error_message=emsg,
                            stdout=stdout[:2000], duration_ms=elapsed())

    if len(proc.stdout) > MAX_STDOUT_BYTES:
        return EngineResult(False, error_type="OutputTooLarge",
                            error_message="Script output exceeded 1 MB.", duration_ms=elapsed())

    if not stdout.strip():
        return EngineResult(False, error_type="NoOutput",
                            error_message="Script finished without printing a JSON result.",
                            duration_ms=elapsed())
    try:
        parsed = json.loads(stdout, parse_constant=_scrub)
    except ValueError as exc:
        return EngineResult(False, error_type="InvalidJSONOutput",
                            error_message=f"stdout was not a single valid JSON document: {exc}",
                            stdout=stdout[:2000], duration_ms=elapsed())

    result_error = _result_error(parsed)
    if result_error:
        return EngineResult(False, error_type="InvalidResult",
                            error_message=result_error, stdout=stdout[:2000],
                            duration_ms=elapsed())

    return EngineResult(True, result=parsed, stdout=stdout, duration_ms=elapsed())
