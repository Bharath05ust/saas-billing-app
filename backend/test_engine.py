"""Offline tests for the sandbox + SDK (no LLM needed). Run: python -m pytest -q  (or python test_engine.py)"""

from engine import extract_code, run_script


def test_valid_script():
    r = run_script("import json\nimport sandbox_sdk\nsubs = sandbox_sdk.get_subscriptions(status='active')\n"
                   "print(json.dumps({'total': len(subs)}))")
    assert r.ok and r.result["total"] > 0


def test_forbidden_imports():
    for mod in ("os", "sys", "requests", "subprocess", "pathlib"):
        r = run_script(f"import {mod}\nprint('{{}}')")
        assert not r.ok and r.error_type == "SecurityViolation", mod


def test_forbidden_escapes():
    for code in (
        "print(().__class__)",
        "print(open('x'))",
        "x = __import__('os')",
        "print('{0.__class__}'.format(1))",
        "import sandbox_sdk\nprint(sandbox_sdk._DATA)",
        "import sandbox_sdk\nprint(sandbox_sdk.__dict__)",
        "while True:\n    pass",
    ):
        r = run_script(code)
        assert not r.ok and r.error_type == "SecurityViolation", code


def test_runtime_error_is_graceful():
    r = run_script("import json\nprint(json.dumps({'x': 1 / 0}))")
    assert not r.ok and r.error_type == "ZeroDivisionError"


def test_timeout(monkeypatch=None):
    import engine
    old = engine.TIMEOUT_SECONDS
    engine.TIMEOUT_SECONDS = 1
    try:
        r = run_script("for i in range(10**12):\n    pass")
    finally:
        engine.TIMEOUT_SECONDS = old
    assert not r.ok and r.error_type == "Timeout"


def test_bad_output():
    assert run_script("print('hello')").error_type == "InvalidJSONOutput"
    assert run_script("x = 1").error_type == "NoOutput"


def test_non_object_json_output():
    for python_value, json_value in (("None", "null"), ("True", "true"), ("42", "42"), ("[]", "[]")):
        r = run_script(f"import json\nprint(json.dumps({python_value}))")
        assert not r.ok and r.error_type == "InvalidResult", json_value


def test_malformed_result_sections():
    scripts = (
        "import json\nprint(json.dumps({'kpis': [None]}))",
        "import json\nprint(json.dumps({'chart': {'type': 'bar', 'labels': ['A'], 'series': [{'name': 'Spend', 'data': []}]}}))",
        "import json\nprint(json.dumps({'table': {'columns': ['A'], 'rows': [[1, 2]]}}))",
    )
    for script in scripts:
        r = run_script(script)
        assert not r.ok and r.error_type == "InvalidResult"


def test_valid_structured_result():
    r = run_script(
        "import json\n"
        "result = {'title': 'Spend', 'summary': 'Summary', 'total': 10,"
        " 'kpis': [{'label': 'MRR', 'value': 10, 'unit': 'usd'}],"
        " 'chart': {'type': 'bar', 'labels': ['Engineering'],"
        " 'series': [{'name': 'MRR', 'data': [10]}]},"
        " 'table': {'columns': ['Department', 'MRR'], 'rows': [['Engineering', 10]]},"
        " 'assumptions': ['Active subscriptions only']}\n"
        "print(json.dumps(result))"
    )
    assert r.ok and r.result["total"] == 10


def test_empty_state():
    r = run_script("import json\nimport sandbox_sdk\nprint(json.dumps({'total': len(sandbox_sdk.get_subscriptions(software_name='Nope'))}))")
    assert r.ok and r.result == {"total": 0}


def test_sdk_math():
    r = run_script(
        "import json\nimport sandbox_sdk\n"
        "subs = sandbox_sdk.get_subscriptions()\n"
        "s = subs[0]\n"
        "print(json.dumps({'full': sandbox_sdk.prorated_cost(s, s['start_date'], s['start_date']),"
        " 'mrr': sandbox_sdk.mrr_at(s, s['start_date']), 'z': sandbox_sdk.safe_divide(1, 0),"
        " 'm': sandbox_sdk.last_n_months(3)}))"
    )
    assert r.ok and r.result["z"] == 0.0 and len(r.result["m"]) == 3
    assert abs(r.result["full"] - r.result["mrr"] * 12 / 365) < 0.01


def test_extract_code_fences():
    assert extract_code("```python\nprint(1)\n```") == "print(1)"
    assert extract_code("print(1)") == "print(1)"


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
