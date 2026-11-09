# UST Financial Insights — Code Mode

UST Code Mode turns natural-language financial questions into Python analysis scripts, runs them in a restricted sandbox against subscription data, and displays the computed results in a dashboard.

The current sample dataset is generated locally by `backend/sandbox_sdk.py`; it is not connected to a live UST or customer billing system. Replace or integrate that data source before using this app for real financial reporting.

```
backend/
  sandbox_sdk.py     data + safe query functions (only door scripts get)
  prompts.py         Orchestrator system prompt (code-only, math + security guardrails)
  sandbox_runner.py  AST validation + restricted builtins + import allow-list
  engine.py          subprocess execution, timeout, error mapping, JSON validation
  app.py             FastAPI: POST /api/query (with one automatic repair retry)
  test_engine.py     offline sandbox tests
frontend/            Next.js dashboard (chat input, loading state, results, script toggle)
```

## Run
```
# backend
cd backend
pip install -r requirements.txt
notepad .env                     # paste your Groq key after GROQ_API_KEY=, then save
.\start_backend.ps1             # starts the backend
python test_engine.py            # sandbox self-test, no API key needed

# frontend (second terminal)
cd frontend
npm install
npm run dev                      # http://localhost:3000  (proxies /api to :8000)
```
Backend settings can be placed in `backend/.env`; copy the keys from `backend/.env.example` if needed. This backend uses Groq's OpenAI-compatible API. Create a key in GroqCloud and set `GROQ_API_KEY`; `GROQ_MODEL` defaults to `openai/gpt-oss-120b`. Other settings include `CODE_MODE_TIMEOUT` (positive seconds; default 15), `CODE_MODE_MAX_ATTEMPTS` (positive integer; default 2), `CORS_ORIGINS`, and frontend `BACKEND_URL`.

On Windows, if PowerShell blocks scripts, run the launcher from `backend` with:
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_backend.ps1`

## Security note
The sandbox is layered hardening (AST allow-list, restricted builtins, scrubbed env, timeout, POSIX rlimits),
not a hard boundary. For production, run `sandbox_runner.py` inside a container/microVM with no network.
