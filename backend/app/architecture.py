"""Self-description of the implemented architecture for the Architecture Explorer.

Component descriptions point at the actual modules; the tool catalogue, state-transition
table, permission matrix and active provider are read live from the running code, so the
explorer cannot drift from the implementation.
"""

from __future__ import annotations

from typing import Any

from app.auth.permissions import permission_matrix_table
from app.tools.registry import ToolRegistry
from app.workflows.states import transition_table

COMPONENTS: list[dict[str, Any]] = [
    {
        "id": "frontend",
        "name": "Next.js Dashboard",
        "layer": "presentation",
        "path": "frontend/src",
        "responsibility": (
            "Operator UI: playground, workflow explorer, approvals, security monitor, "
            "Failure Lab, audit timeline. Holds no business rules and is never the security "
            "boundary."
        ),
    },
    {
        "id": "api",
        "name": "FastAPI API layer",
        "layer": "api",
        "path": "backend/app/api",
        "responsibility": (
            "HTTP contracts, request validation, error mapping and authentication "
            "dependencies. Delegates all business logic to services."
        ),
    },
    {
        "id": "auth",
        "name": "Authentication & authorization",
        "layer": "security",
        "path": "backend/app/auth",
        "responsibility": (
            "JWT issuance/verification, roles, the permission matrix and principals "
            "(users, the least-privilege agent principal, system)."
        ),
    },
    {
        "id": "orchestrator",
        "name": "Workflow orchestrator",
        "layer": "agent",
        "path": "backend/app/agents/orchestrator.py",
        "responsibility": (
            "Explicit, checkpointed state machine: one step per state, validated "
            "transitions, commit after every step, resume/recovery."
        ),
    },
    {
        "id": "provider",
        "name": "AI provider abstraction",
        "layer": "agent",
        "path": "backend/app/agents",
        "responsibility": (
            "Interprets the untrusted customer message into a structured proposal. "
            "Deterministic mock by default; Anthropic / OpenAI-compatible optional."
        ),
    },
    {
        "id": "scanner",
        "name": "Untrusted content scanner",
        "layer": "security",
        "path": "backend/app/agents/scanner.py",
        "responsibility": (
            "Heuristic detector for instruction-like text; escalates to human review "
            "and records security events. Not a security boundary."
        ),
    },
    {
        "id": "tools",
        "name": "Tool registry",
        "layer": "agent",
        "path": "backend/app/tools",
        "responsibility": (
            "Typed tools with permission + workflow-state gating, argument validation, "
            "bounded retries and audit events for every outcome."
        ),
    },
    {
        "id": "policy",
        "name": "Deterministic policy engine",
        "layer": "business",
        "path": "backend/app/policies",
        "responsibility": (
            "Pure refund eligibility rules (status, window, balance, tiers) over "
            "trusted order facts. Versioned, stored configuration."
        ),
    },
    {
        "id": "approvals",
        "name": "Approval service",
        "layer": "governance",
        "path": "backend/app/approvals",
        "responsibility": (
            "Human-in-the-loop approvals bound to workflow, action, order and amount; "
            "expiry, invalidation and role-checked decisions."
        ),
    },
    {
        "id": "workflows",
        "name": "Workflow persistence",
        "layer": "business",
        "path": "backend/app/workflows",
        "responsibility": ("Workflow records, the transition table, checkpoints and cancellation."),
    },
    {
        "id": "business",
        "name": "Business operations",
        "layer": "business",
        "path": "backend/app/services/business.py",
        "responsibility": (
            "Customers, orders, the simulated payment gateway and the idempotent "
            "refund execution guarded by a unique constraint."
        ),
    },
    {
        "id": "audit",
        "name": "Audit & observability",
        "layer": "observability",
        "path": "backend/app/observability",
        "responsibility": (
            "Structured audit events written in the same transaction as the change "
            "they describe; metrics computed from stored records; JSON logging."
        ),
    },
    {
        "id": "lab",
        "name": "Failure Lab & failure injection",
        "layer": "evaluation",
        "path": "backend/app/evaluations",
        "responsibility": (
            "Six reproducible scenarios with executable assertions, plus per-workflow "
            "and global fault injection points."
        ),
    },
    {
        "id": "database",
        "name": "Database (PostgreSQL / SQLite)",
        "layer": "data",
        "path": "backend/app/models, backend/migrations",
        "responsibility": (
            "Source of truth for customers, orders, workflows, approvals, executions "
            "and audit events. Alembic-managed schema."
        ),
    },
]

EDGES: list[dict[str, str]] = [
    {"source": "frontend", "target": "api", "label": "HTTPS / JSON"},
    {"source": "api", "target": "auth", "label": "authenticate + authorize"},
    {"source": "api", "target": "orchestrator", "label": "submit / resume / decide"},
    {"source": "api", "target": "workflows", "label": "read"},
    {"source": "api", "target": "approvals", "label": "read"},
    {"source": "api", "target": "audit", "label": "events + metrics"},
    {"source": "api", "target": "lab", "label": "run scenarios"},
    {"source": "orchestrator", "target": "provider", "label": "interpret (once)"},
    {"source": "orchestrator", "target": "scanner", "label": "scan message"},
    {"source": "orchestrator", "target": "tools", "label": "execute via gate"},
    {"source": "orchestrator", "target": "workflows", "label": "transition + checkpoint"},
    {"source": "orchestrator", "target": "approvals", "label": "auto-approve"},
    {"source": "tools", "target": "auth", "label": "permission check"},
    {"source": "tools", "target": "policy", "label": "evaluate"},
    {"source": "tools", "target": "approvals", "label": "request / read"},
    {"source": "tools", "target": "business", "label": "orders / refund"},
    {"source": "tools", "target": "audit", "label": "tool events"},
    {"source": "lab", "target": "orchestrator", "label": "drives real workflows"},
    {"source": "lab", "target": "tools", "label": "fault injection"},
    {"source": "approvals", "target": "audit", "label": "approval events"},
    {"source": "workflows", "target": "database", "label": "persist"},
    {"source": "business", "target": "database", "label": "transactions"},
    {"source": "audit", "target": "database", "label": "append"},
    {"source": "policy", "target": "database", "label": "versioned config"},
]

TRUST_BOUNDARIES: list[dict[str, Any]] = [
    {
        "name": "Browser ↔ API",
        "description": "Everything from the browser is untrusted until the JWT is verified and the "
        "permission matrix allows the action. The UI hides buttons; the API enforces.",
    },
    {
        "name": "Customer message ↔ Agent",
        "description": "The customer's text is data. It is delimited in the prompt, scanned, and "
        "never allowed to change which tools the agent may call.",
    },
    {
        "name": "Agent output ↔ Business logic",
        "description": (
            "Interpretations and proposed tool calls are validated against the database, "
            "gated by permission + workflow state, and policy is evaluated deterministically."
        ),
    },
    {
        "name": "Approval ↔ Execution",
        "description": "Execution requires an approved approval bound to the same workflow, order "
        "and amount; the database allows one execution per workflow.",
    },
]


def describe(registry: ToolRegistry, provider_info: dict[str, str]) -> dict[str, Any]:
    return {
        "components": COMPONENTS,
        "edges": EDGES,
        "trust_boundaries": TRUST_BOUNDARIES,
        "tools": registry.descriptors(),
        "state_transitions": transition_table(),
        "permission_matrix": permission_matrix_table(),
        "ai_provider": provider_info,
    }
