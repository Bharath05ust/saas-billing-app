import app as backend
import openai
from fastapi.testclient import TestClient


client = TestClient(backend.app)


def test_health_and_read_only_endpoints():
    assert client.get("/api/health").status_code == 200

    overview = client.get("/api/overview")
    assert overview.status_code == 200
    data = overview.json()
    assert data["kpis"]["arr"] == round(data["kpis"]["mrr"] * 12, 2)
    assert len(data["months"]) == len(data["mrr_series"]) == 12
    assert len(data["movements"]) == 11

    subscriptions = client.get("/api/subscriptions")
    assert subscriptions.status_code == 200
    assert subscriptions.json()["items"]


def test_query_repairs_failed_script(monkeypatch):
    scripts = iter((
        "print('not JSON')",
        "import json\nprint(json.dumps({'title': 'Test', 'summary': 'Done', 'total': 1}))",
    ))
    monkeypatch.setattr(backend, "generate_script", lambda messages: next(scripts))

    response = client.post("/api/query", json={"query": "Show a test result"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"]
    assert data["result"]["total"] == 1
    assert len(data["attempts"]) == 2
    assert not data["attempts"][0]["ok"]
    assert data["attempts"][1]["ok"]


def test_query_rejects_short_questions():
    assert client.post("/api/query", json={"query": "hi"}).status_code == 422


def test_generate_script_uses_groq_chat_completions(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {
                "choices": [type("Choice", (), {
                    "finish_reason": "stop",
                    "message": type("Message", (), {"content": "print('script')"})(),
                })()],
            })()

    class FakeOpenAI:
        def __init__(self, *, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(backend, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(backend, "_client", None)
    monkeypatch.setattr(backend, "_client_api_key", None)

    result = backend.generate_script([{"role": "user", "content": "Give me a result"}])

    assert result == "print('script')"
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"
    assert captured["model"] == backend.MODEL
    assert captured["model"] == "openai/gpt-oss-120b"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1]["content"] == "Give me a result"


def test_generate_script_requires_groq_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    try:
        backend.generate_script([])
    except backend.LLMError as exc:
        assert "GROQ_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected missing Groq API key to be reported")


def test_generate_script_explains_provider_payment_required(monkeypatch):
    class PaymentRequiredError(openai.APIStatusError):
        def __init__(self):
            Exception.__init__(self, "Payment Required")

        @property
        def status_code(self):
            return 402

    class FakeCompletions:
        def create(self, **kwargs):
            raise PaymentRequiredError()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(backend, "_client", FakeClient())
    monkeypatch.setattr(backend, "_client_api_key", "test-key")

    try:
        backend.generate_script([])
    except backend.LLMError as exc:
        assert "402 Payment Required" in str(exc)
        assert "Groq account billing" in str(exc)
    else:
        raise AssertionError("Expected provider 402 to be reported")
