# Contributing to AgentGuard

Thank you for helping build AgentGuard! This project is maintained by The GenAI Foundry community and is designed to be read and extended by learners. Contributions of every size are welcome: a typo fix, a test, a new scanner pattern or a whole Failure Lab scenario.

## Ground rules

- **Fictional data only.** Never add real customer information, real payment integrations or real credentials, even in tests or screenshots.
- **Security decisions live in backend code.** Not in prompts, not in the UI. If you add a capability, add its permission check and a negative test.
- **No fake results.** Metrics come from stored data; Failure Lab results come from assertions. Never hard-code a success.
- **Small, focused pull requests** with tests are reviewed fastest.

## 1. Run the project

The quickest path is Docker (`docker compose up --build`); see the [README](README.md#quick-start-docker-recommended). For development you will usually run the two apps locally:

**Windows (PowerShell)**
```powershell
.\scripts\setup-local.ps1
.\scripts\start-backend.ps1     # terminal 1, http://127.0.0.1:8000 (API docs at /docs)
.\scripts\start-frontend.ps1    # terminal 2, http://localhost:3000
```

**macOS / Linux**
```bash
./scripts/setup-local.sh
cd backend && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

Requirements: Python 3.12+, Node.js 22.22+ or 24.15+, npm. The backend uses SQLite locally and creates its tables on start-up. Delete `backend/agentguard.db` to start from fresh seed data.

## 2. Understand the codebase

Start with these files, in this order:

1. `backend/app/workflows/states.py`: the state machine (about 100 lines).
2. `backend/app/agents/orchestrator.py`: one step function per state.
3. `backend/app/tools/registry.py`: how every tool call is authorized, validated, retried and audited.
4. `backend/app/tools/refund_tools.py`: the agent's tools.
5. `backend/app/policies/engine.py`: pure policy rules.
6. `backend/app/approvals/service.py`: human-in-the-loop controls.
7. `backend/app/services/business.py`: `RefundService.execute`, the idempotent money movement.
8. `backend/app/evaluations/failure_lab.py`: scenarios as executable assertions.

[ARCHITECTURE.md](ARCHITECTURE.md) explains how they fit together; [LEARNING_GUIDE.md](LEARNING_GUIDE.md) explains why.

### Conventions

- **Backend:** Python 3.12, type hints everywhere, Pydantic for I/O, SQLAlchemy 2 typed models. Money is integer **paise**. Datetimes are timezone-aware UTC (`app.database.utcnow()`). Business logic belongs in services, not route handlers. Raise the domain errors in `app/errors.py`; the API maps them to HTTP status codes.
- **Frontend:** TypeScript strict mode, App Router client pages, API calls through `src/lib/api.ts`, types in `src/lib/types.ts` (mirror `backend/app/schemas/api.py`), theme tokens in `src/app/globals.css`.
- **Formatting and linting:** `ruff format` + `ruff check` (backend), `npm run lint` (frontend).

## 3. Common contributions

### Add a tool

1. Define strict input/output models in `backend/app/tools/refund_tools.py` (inputs extend `StrictModel` so unknown fields are rejected).
2. Write the handler. Scope any data access to `ctx.workflow`'s customer.
3. Register a `ToolSpec` in `build_registry()` with the **narrowest** permission and, if it has side effects, the workflow states in which it may run.
4. Grant the permission to the agent in `backend/app/auth/permissions.py` *only if the agent truly needs it*.
5. Test: allowed path, denied by permission, denied by state, invalid arguments, and audit events (`backend/tests/test_tool_registry.py` has examples).

### Add a policy rule

Add the rule to `PolicyEngine.evaluate`, append a `PolicyRuleResult`, add a reason code, and expose any threshold in `PolicyConfig`. Write boundary tests in `backend/tests/test_policy_engine.py` (exactly at the limit, one paisa either side).

### Add a Failure Lab scenario

1. Write a runner `def run_my_scenario(ctx: LabRunContext) -> None` in `backend/app/evaluations/failure_lab.py`. Use `ctx.create_lab_order(...)` for disposable data, drive real workflows through `ctx.orchestrator`, and record each expectation with `ctx.check(name, condition, detail)`.
2. Add a `Scenario(...)` entry to `SCENARIOS` with the initial request, expected safe behavior and explanation.
3. The parametrized test `test_each_scenario_passes_with_real_assertions` picks it up automatically. Make sure it is repeatable (run it twice).

### Add a scanner pattern

Add a regex to `_PATTERNS` in `backend/app/agents/scanner.py`, then add a true-positive example to `INJECTIONS` **and** a similar benign sentence to `BENIGN` in `backend/tests/test_prompt_injection.py`. Remember: the scanner only escalates; it is never the security boundary.

### Change the database schema

Edit the model, then generate a migration from `backend/`:
```bash
DATABASE_URL=sqlite:///./migration-check.db alembic upgrade head
DATABASE_URL=sqlite:///./migration-check.db alembic revision --autogenerate -m "describe the change"
```
Review the generated file (replace `app.database.UTCDateTime()` with `sa.DateTime(timezone=True)`), then run `pytest tests/test_providers_and_infra.py::test_alembic_migrations_match_models`.

### Add a dashboard page

Create `frontend/src/app/<page>/page.tsx` as a client component wrapped in `<AppShell>`, load data with `useQuery` from `src/lib/use-query.ts`, and add a link in `src/components/app-shell.tsx`. Hide controls the user lacks permission for with `useAuth().can(...)`, but make sure the API enforces the same rule.

## 4. Write tests

```bash
cd backend && .venv/bin/pytest                      # all backend tests (~30 s)
cd backend && .venv/bin/pytest -k approval          # a subset
cd frontend && npm test                             # Vitest unit tests
cd frontend && npm run test:e2e                     # Playwright (start both apps first)
```

On Windows use `.venv\Scripts\python.exe -m pytest`, or `.\scripts\test-all.ps1` for everything except end-to-end tests.

- Every security rule needs a **negative** test (the forbidden thing is refused, audited, and changes nothing).
- Concurrency-sensitive code should be tested with a second session or threads (see `backend/tests/test_concurrency.py`).
- To run the backend suite against PostgreSQL, set `AGENTGUARD_TEST_DATABASE_URL` to a **dedicated, disposable** database (the tests drop and recreate its tables).
- For Playwright with an installed Chrome instead of the bundled Chromium: `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`.

## 5. Submit a pull request

1. Fork the repository and create a branch: `feat/approval-expiry-scenario`, `fix/scanner-false-positive`, `docs/demo-guide-typo`.
2. Make your change with tests and documentation updates.
3. Run the checks: backend `ruff check app tests && ruff format --check app tests && pytest`; frontend `npm run lint && npm test && npm run build`.
4. Open a pull request and fill in the template. CI runs backend tests on SQLite and PostgreSQL, frontend checks, Playwright and a Docker build.
5. A maintainer reviews it. Expect questions about security implications; that is the point of the project.

## 6. Where to start

**Good first issues**
- Add a playground example and its expected outcome (`PLAYGROUND_EXAMPLES` in `backend/app/api/routes_lab_admin.py`).
- Add a scanner pattern plus true-positive and benign tests.
- Improve accessibility labels or empty states on a dashboard page.
- Fix or clarify anything confusing in the documentation.

**Intermediate**
- An admin page for global failure injections (the API already exists).
- A policy editor page using `PUT /api/policies`.
- Audit timeline export (JSON/CSV).

**Advanced**
- An approval-expiry or policy-change-while-pending Failure Lab scenario.
- An evaluation harness comparing a real LLM against the mock on the same scenarios.
- OIDC login with HttpOnly cookie sessions.
- A second business domain reusing the orchestrator, registry and approvals.

## 7. Reporting bugs and security issues

Use the **Bug report** issue template with steps to reproduce (fictional data only). For a vulnerability in AgentGuard's own code, contact the maintainers privately instead of opening a public issue.

By contributing, you agree that your contributions are licensed under the project's [license](LICENSE).
