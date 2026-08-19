# Repository Guidelines

## Project Structure

- `backend/app/` contains the canonical FastAPI application. Use `main.py` for API routes, `models/` for Pydantic schemas, and `services/` for parsing, filtering, LLM calls, task storage, and section extraction.
- `frontend/index.html` is the production single-page UI; `frontend/nginx.conf` provides the reverse proxy and SSE settings.
- `data/` stores runtime uploads, task state, CSV results, and history. Treat its contents as generated/user data.
- The root `backend/` is the canonical service used by `docker-compose.yml`.

## Build and Development Commands

```bash
docker-compose up -d --build       # Build and start backend + Nginx frontend
cd backend && pip install -r requirements.txt
cd backend && python run.py         # Local API at http://localhost:8000
python -m compileall -q backend/app # Check Python syntax/bytecode compilation
cd frontend && python -m http.server 8080  # Simple static frontend server
```

Run backend commands from `backend/` when using the local entry point. Use `.env.example` to create `.env` before starting the API.

## Coding Style & Naming

Use four-space indentation, type hints for public functions, `snake_case` for functions/variables, and `PascalCase` for classes. Keep model-specific logic isolated in the relevant service and preserve the existing `m1`, `m3`, `m5`, and `m10` naming. No formatter or linter is configured; keep changes small, readable, and compatible with Python 3.11. Match the existing frontend’s plain HTML/CSS/JavaScript style and escape user-provided values rendered into HTML.

## Commits & Pull Requests

No repository-specific Git history is available. Use concise imperative messages such as `fix: prevent duplicate upload overwrites` or `docs: clarify deployment paths`. PRs should describe the behavior change, list validation commands and results, link an issue when applicable, and include UI screenshots for frontend changes. Never commit `.env`, API keys, or generated runtime data.
