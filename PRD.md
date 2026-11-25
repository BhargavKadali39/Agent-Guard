# AgentGuard: Product Requirements

## 1. Summary

AgentGuard is an open-source AI engineering platform from The GenAI Foundry. It simulates an e-commerce company's refund operations, where an AI agent interprets customer requests and backend systems decide, approve and execute. It exists to teach, through working software, how engineers build agents that are **reliable, observable, secure, recoverable and subject to human control**, and to anchor live technical workshops.

## 2. Problem

Most AI tutorials stop at "call an LLM API" or "build a chatbot". Developers rarely see what happens when an agent receives malicious instructions, hits a failing tool, attempts an action it is not allowed to take, crashes mid-operation or needs a human decision. Without a safe place to watch these failures, teams either over-trust agents or never deploy them.

## 3. Goals

1. Demonstrate, with real code and tests, that the LLM is never the final authority for sensitive operations.
2. Make agent behavior **observable**: what the AI proposed, what policy permitted, what a human approved and what the system executed.
3. Provide reproducible failure demonstrations (the Failure Lab) whose pass/fail status comes from executable assertions.
4. Be easy to run on a developer laptop (Docker, or locally with SQLite) with **no paid API keys**.
5. Be a credible open-source codebase: modular, typed, tested, documented, contributor-friendly.

## 4. Non-goals

- Real payments, real customer data or integration with real commerce systems.
- Production certification or enterprise security assurances.
- A general-purpose agent framework or a chatbot UI.
- Multiple business domains in v1 (refunds only).
- Distributed infrastructure (queues, microservices) that the problem does not need.

## 5. Users

| Persona | Needs |
|---|---|
| Workshop attendee / student | See an agent work and fail safely; understand the controls; read approachable code |
| Developer / AI engineer | Concrete, reusable patterns: tool gating, idempotency, approvals, audit, evaluation |
| Workshop presenter | A reliable, reproducible demo script with predictable outcomes |
| Open-source contributor | Clear structure, tests, and well-scoped issues to pick up |
| Engineering / product lead | Evidence of what controls make agent autonomy acceptable |

Inside the simulation, four staff roles exist: **Support Operator**, **Reviewer**, **Senior Reviewer** and **Administrator**, plus the **agent** itself as a least-privilege principal.

## 6. Functional requirements

### Agent workflow
- **FR-1** A staff user can submit a refund request for a (fictional) customer with a free-text message.
- **FR-2** The agent interprets the request via a provider abstraction: a deterministic mock (default) or an optional real LLM (Anthropic, or any OpenAI-compatible endpoint) configured by environment variables.
- **FR-3** The agent acts only through registered tools with documented purpose, validated input and output schemas, explicit authorization requirements, defined failure behavior and audit logging.
- **FR-4** Workflows follow an explicit state machine (`CREATED`, `ANALYZING`, `VERIFYING`, `POLICY_CHECK`, `AWAITING_APPROVAL`, `APPROVED`, `EXECUTING`, `COMPLETED`, `REJECTED`, `FAILED`, `CANCELLED`); arbitrary transitions are refused.
- **FR-5** The agent's interpretation is verified against trusted order data before any decision; discrepancies, low confidence and suspicious content force human review.

### Policy
- **FR-6** A deterministic, configurable, versioned policy engine decides eligibility: eligible fulfillment status, refund window, refundable balance, approval tiers (≤ ₹2,000 auto; ≤ ₹10,000 reviewer; > ₹10,000 senior reviewer), and an optional exception workflow.
- **FR-7** Ineligible requests are rejected unless the exception workflow is enabled, in which case a senior reviewer decides.

### Approvals
- **FR-8** Restricted refunds create approval requests bound to a specific workflow, action, order and amount, with expiry.
- **FR-9** Authorized reviewers approve or reject with comments; decisions record the reviewer's identity; unauthorized users are refused and the refusal is audited.
- **FR-10** Workflow state persists while waiting; approval resumes execution; rejection makes execution impossible; cancellation invalidates pending approvals.

### Security
- **FR-11** Users authenticate; every protected action is authorized on the server via an explicit permission matrix.
- **FR-12** Untrusted customer text is separated from trusted instructions and can never widen the agent's permissions.
- **FR-13** Security events (injection suspected, denied tool calls, denied decisions, blocked transitions, invalidated approvals) are recorded and viewable.

### Reliability
- **FR-14** Workflows checkpoint every step and can resume after a failure, an interruption or an application restart.
- **FR-15** Safe operations retry with bounds; operations that must not happen twice are idempotent (submissions and refund executions).
- **FR-16** A controlled failure-injection mechanism supports demonstrations (tool, gateway, database, interruption and model faults).

### Observability and evaluation
- **FR-17** Structured audit events capture workflow id, timestamp, category, tool, duration, authorization outcome and workflow state.
- **FR-18** The dashboard provides Overview, Agent Playground, Workflow Explorer, Approval Center, Security Monitor, Failure Lab, Audit Timeline and Architecture Explorer pages.
- **FR-19** Overview metrics (total, completed, pending approvals, failed, blocked unauthorized actions, average duration) are computed from stored records.
- **FR-20** The Failure Lab runs six scenarios (prompt injection, unauthorized tool execution, duplicate refund request, workflow interruption, human approval rejection, agent decision error), each showing the request, expected behavior, observed behavior, events and an assertion-based pass/fail with an explanation.

## 7. Nonfunctional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Runs with `docker compose up --build`, or locally with Python 3.12 + Node.js and SQLite; works fully offline in mock mode |
| NFR-2 | Typed interfaces and schemas (Pydantic, TypeScript); consistent JSON error format |
| NFR-3 | Database migrations (Alembic); indexes on hot lookups; transactions around sensitive state changes |
| NFR-4 | No hard-coded secrets; environment-based configuration; production refuses weak JWT secrets |
| NFR-5 | Structured logging (JSON option); no unnecessary personal data in logs |
| NFR-6 | Automated backend, frontend and end-to-end tests; CI on every push and pull request |
| NFR-7 | Clearly labelled as a simulation; no fabricated metrics or hard-coded test results |
| NFR-8 | Dark, accessible, responsive dashboard; branding replaceable without code changes elsewhere |
| NFR-9 | Modular monolith; documented architecture decisions |

## 8. Acceptance criteria

Each criterion is verified by automated tests (file: test name). "e2e" refers to `frontend/e2e/*.spec.ts`.

| # | Criterion | Verified by |
|---|---|---|
| 1 | A customer refund request can be created | `test_api.py`: `test_submit_workflow_requires_permission_and_runs`; e2e: *auto-tier refund completes end to end* |
| 2 | The agent or mock provider can interpret the request | `test_orchestrator_flows.py`: `test_auto_tier_completes_without_human`; `test_providers_and_infra.py`: `test_anthropic_provider_parses_tool_use`, `test_openai_compatible_provider_parses_function_call` |
| 3 | Order information can be retrieved | `test_tool_registry.py`: `test_data_scoping_denies_other_customers_orders`; `test_api.py`: `test_commerce_and_policy_endpoints` |
| 4 | Business policies are evaluated correctly | `test_policy_engine.py` (₹2,000 / ₹2,000.01 / ₹2,001 / ₹10,000 / ₹10,000.01 / ₹10,001, window, statuses, balance) |
| 5 | Ineligible requests are blocked | `test_orchestrator_flows.py`: `test_ineligible_requests_are_rejected_by_policy` |
| 6 | Requests requiring approval remain pending | `test_orchestrator_flows.py`: `test_reviewer_tier_waits_for_approval`, `test_senior_tier` |
| 7 | Authorized reviewers can approve requests | `test_approvals.py`: `test_reviewer_approval_executes_refund_with_identity`; e2e: *reviewer approves a pending refund* |
| 8 | Unauthorized users cannot approve requests | `test_approvals.py`: `test_operator_cannot_approve_and_denial_is_audited`, `test_reviewer_cannot_decide_senior_tier`, `test_agent_principal_cannot_approve`; `test_api.py`: `test_approval_flow_over_http` |
| 9 | Rejected requests cannot proceed to execution | `test_approvals.py`: `test_rejection_is_final`; Failure Lab scenario 5 |
| 10 | Approved requests trigger simulated refund execution | `test_approvals.py`: `test_reviewer_approval_executes_refund_with_identity` |
| 11 | Duplicate execution requests cannot create duplicate refunds | `test_idempotency_and_recovery.py`: `test_replaying_execution_has_no_side_effects`, `test_database_unique_constraint_blocks_second_execution`, `test_concurrent_resumes_execute_exactly_once`; `test_concurrency.py`; Failure Lab scenario 3 |
| 12 | Workflow interruptions can be recovered from safely | `test_idempotency_and_recovery.py`: `test_interruption_then_resume_from_every_point`, `test_restart_recovers_in_flight_workflows`; Failure Lab scenario 4 |
| 13 | Prompt injection examples cannot bypass authorization or policy | `test_prompt_injection.py`; Failure Lab scenarios 1 and 2; e2e: *prompt injection is flagged, denied and escalated* |
| 14 | Relevant actions appear in audit records | assertions on audit events throughout `test_orchestrator_flows.py`, `test_approvals.py`, `test_tool_registry.py` |
| 15 | Dashboard metrics reflect stored records | `test_api.py`: `test_metrics_reflect_stored_records` |
| 16 | Every Failure Lab scenario has executable validation | `test_failure_lab.py`: `test_each_scenario_passes_with_real_assertions`, `test_a_broken_invariant_is_reported_not_hidden` |
| 17 | The application starts through documented commands | README quick start; CI `docker` job builds the images; startup is exercised by every API test |
| 18 | The test suite runs through documented commands | README "Running the tests"; `scripts/test-all.ps1`, `scripts/test-all.sh`; CI workflow |

## 9. Success measures

- A newcomer can start the stack and complete the demo guide in under 30 minutes.
- All six Failure Lab scenarios pass on a fresh install.
- Workshop attendees can explain, with reference to the code, why a manipulated model could not issue an unauthorized refund.
- Contributors can add a tool or a Failure Lab scenario by following CONTRIBUTING.md without changing unrelated modules.

## 10. Future scope

Additional business domains (order cancellations, account changes), multi-step agent plans with a graph orchestrator, evaluation suites against real models, an identity-provider integration, and a policy editor in the dashboard.
