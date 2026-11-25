# AgentGuard Implementation Plan and Status

This file records how AgentGuard was built in milestones, what each milestone delivered, how it was verified, and what remains. Statuses reflect checks that were actually executed; anything that could not be executed is listed explicitly.

## Architectural proposal (as implemented)

1. **Technology:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic and PyJWT on Python 3.12+; PostgreSQL 17 (Docker) or SQLite (local); Next.js 16 with TypeScript, Tailwind CSS v4, React Flow and Recharts; pytest, Vitest and Playwright; Docker Compose and GitHub Actions.
2. **Core modules:** API, auth, orchestrator, AI providers, scanner, tool registry, policy engine, approvals, workflow persistence, business operations, observability, Failure Lab (see [ARCHITECTURE.md](ARCHITECTURE.md)).
3. **Database entities:** users, customers, products, orders, refund_policies, workflows, approval_requests, refund_executions, audit_events, lab_runs.
4. **Agent state machine:** `CREATED → ANALYZING → VERIFYING → POLICY_CHECK → AWAITING_APPROVAL → APPROVED → EXECUTING → COMPLETED`, plus `REJECTED`, `FAILED` (resumable or not) and `CANCELLED`.
5. **Security boundaries:** browser ↔ API, customer text ↔ agent, agent output ↔ business logic, approval ↔ execution.
6. **Orchestration choice:** an explicit checkpointed state machine rather than LangGraph; trade-offs are documented in ARCHITECTURE.md §10.
7. **Primary risks:** see the risk register below.

## Milestones

| # | Milestone | Status | Delivered |
|---|---|---|---|
| 1 | Architecture and foundation | ✅ Done | Repository layout, configuration, database layer, models, Alembic migration, test fixtures, planning documents |
| 2 | Working business system (no LLM) | ✅ Done | Customers/orders/products, policy engine with boundary tests, simulated payment gateway, idempotent refund execution, workflow state machine and persistence |
| 3 | Agent integration | ✅ Done | Provider abstraction, deterministic mock, Anthropic and OpenAI-compatible adapters, structured interpretation, tool registry, orchestrator |
| 4 | Approvals and security | ✅ Done | JWT authentication, permission matrix, role-bound approvals with expiry/invalidation, tool authorization, security events |
| 5 | Reliability engineering | ✅ Done | Checkpoints, resume, startup recovery, bounded retries, failure injection, processing leases, compare-and-swap transitions and decisions |
| 6 | Observability and Failure Lab | ✅ Done | Audit trail, metrics, security monitor API, six assertion-backed scenarios, architecture self-description |
| 7 | UI, deployment, documentation | ✅ Done | Eight dashboard pages, Dockerfiles, Compose, CI workflow, issue/PR templates, documentation set, helper scripts |
| 8 | Validation | ✅ Done (with the exceptions listed below) | See "Validation results" |

## Validation results

These checks were run and passed during development:

| Check | Command | Result |
|---|---|---|
| Backend lint and format | `ruff check app tests` / `ruff format --check` | clean |
| Backend tests, SQLite, Python 3.13 | `pytest` | 137 passed |
| Backend tests, SQLite, **Python 3.12** | `pytest` | 137 passed |
| Backend tests, **PostgreSQL** | `AGENTGUARD_TEST_DATABASE_URL=… pytest` | 137 passed |
| Concurrency tests repeated for flakiness | 15× on SQLite, 10× on PostgreSQL | 0 failures |
| Migration matches models | `test_alembic_migrations_match_models`, plus manual upgrade/downgrade on PostgreSQL | no differences |
| Dependency resolution for Windows + Python 3.12 | `uv pip compile --python-platform x86_64-pc-windows-msvc --python-version 3.12 --only-binary :all:` | resolves with wheels only |
| Frontend type-check and lint | `tsc --noEmit`, `eslint` | clean |
| Frontend unit tests | `vitest run` | 7 passed |
| Frontend production build | `next build` | succeeds |
| End-to-end tests (Chrome) | `playwright test` against a running stack | 9 passed (against both SQLite and PostgreSQL backends) |
| Failure Lab through the UI | "Run all scenarios" | 6/6 passed |
| Docker images (step-by-step reproduction) | every Dockerfile instruction replayed in a clean directory: dependency install, `alembic upgrade head` on PostgreSQL, the container `CMD`, the `HEALTHCHECK` command, clean `npm ci`, standalone build and server, API proxy | all succeeded |

### Not executed in the build environment

| Item | Why | How it is covered |
|---|---|---|
| `docker compose build` / `up` | No Docker daemon was available in the build sandbox | Each Dockerfile step was reproduced manually (above); the CI `docker` job builds both images; run it locally to confirm |
| GitHub Actions workflow | Requires a GitHub repository | YAML validated; every command in it was run locally |
| PowerShell helper scripts | No PowerShell in the build sandbox | Scripts are ASCII-only and use standard cmdlets; run them on Windows to confirm |
| Real LLM providers against live APIs | No API keys were used | Adapters are tested with mocked HTTP responses, including error paths |

## Risk register

| Risk | Mitigation |
|---|---|
| Scope too large to finish correctly | Milestones ordered so business correctness (policy, idempotency, recovery) came before UI breadth |
| Mock provider too simplistic to demonstrate real failures | `comply` mode simulates a fully manipulated model; provider faults simulate misreads and misclassification; real providers optional |
| Failure Lab results drifting into "decoration" | Results come only from assertions; a test proves a broken invariant is reported as a failure |
| Concurrency bugs hidden by timing | Leases, compare-and-swap and row locks; concurrency tests repeated many times on two databases |
| Version incompatibilities across the stack | Exact backend pins verified on Python 3.12/3.13 and resolved for Windows; lockfile includes Windows and Alpine native binaries |
| Windows-specific issues | `127.0.0.1` instead of `localhost` for the API proxy; PowerShell scripts; LF/CRLF rules in `.gitattributes` |

## Roadmap and contribution ideas

**Beginner-friendly**
- Add a new playground example request and its expected outcome.
- Add a scanner pattern with tests for both a true positive and a benign near-miss.
- Improve empty states and accessibility labels in the dashboard.
- Add a "copy workflow id" button in the Workflow Explorer.

**Intermediate**
- A dashboard page for administrators to manage global failure injections (the API exists).
- A policy editor page using `PUT /api/policies` with validation feedback.
- Export of the audit timeline as JSON/CSV.
- Store global failure injections in the database so they work across multiple API processes.

**Advanced**
- A seventh Failure Lab scenario, for example *approval expiry* or *policy change while awaiting approval*.
- An evaluation harness that runs the same scenarios against a real LLM and reports differences from the mock.
- OIDC login and HttpOnly cookie sessions.
- A second business domain (order cancellation) reusing the orchestrator, registry and approvals.
