# AgentGuard backend

FastAPI service implementing AgentGuard's agent orchestration, tool registry, policy engine, approvals, audit trail and Failure Lab. See the [project README](../README.md) and [ARCHITECTURE.md](../ARCHITECTURE.md).

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\python.exe -m pip install -e ".[dev]"
cp .env.example .env                        # optional; defaults work (SQLite, mock AI provider)
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
.venv/bin/pytest                            # 137 tests
```

- API docs: http://127.0.0.1:8000/docs
- PostgreSQL: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db`, then `alembic upgrade head`.
- Configuration: `app/config.py` (every setting can be set as an environment variable of the same name in upper case).
