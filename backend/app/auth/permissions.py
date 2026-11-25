"""Roles, permissions and the permission matrix.

Authorization is enforced in backend code (API dependencies, the tool registry and the
approval service). The frontend only *reads* this matrix to hide controls a user cannot
use; hiding is a courtesy, not a security control.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Role(StrEnum):
    SUPPORT_OPERATOR = "support_operator"
    REVIEWER = "reviewer"
    SENIOR_REVIEWER = "senior_reviewer"
    ADMINISTRATOR = "administrator"
    # The autonomous agent runs under its own least-privilege principal.
    AGENT = "agent"


HUMAN_ROLES: tuple[Role, ...] = (
    Role.SUPPORT_OPERATOR,
    Role.REVIEWER,
    Role.SENIOR_REVIEWER,
    Role.ADMINISTRATOR,
)


class Permission(StrEnum):
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_RESUME = "workflow:resume"
    WORKFLOW_CANCEL = "workflow:cancel"
    CUSTOMER_READ = "customer:read"
    CUSTOMER_UPDATE = "customer:update"
    ORDER_READ = "order:read"
    POLICY_READ = "policy:read"
    POLICY_EVALUATE = "policy:evaluate"
    POLICY_MANAGE = "policy:manage"
    APPROVAL_REQUEST = "approval:request"
    APPROVAL_READ = "approval:read"
    APPROVAL_DECIDE_STANDARD = "approval:decide:standard"
    APPROVAL_DECIDE_SENIOR = "approval:decide:senior"
    REFUND_EXECUTE = "refund:execute"
    AUDIT_READ = "audit:read"
    SECURITY_READ = "security:read"
    METRICS_READ = "metrics:read"
    FAILURE_LAB_RUN = "failure_lab:run"
    ADMIN_FAILURE_INJECTION = "admin:failure_injection"
    ADMIN_SEED = "admin:seed"


_STAFF_READ = {
    Permission.WORKFLOW_READ,
    Permission.CUSTOMER_READ,
    Permission.ORDER_READ,
    Permission.POLICY_READ,
    Permission.APPROVAL_READ,
    Permission.AUDIT_READ,
    Permission.METRICS_READ,
}

PERMISSION_MATRIX: dict[Role, frozenset[Permission]] = {
    Role.SUPPORT_OPERATOR: frozenset(
        _STAFF_READ
        | {
            Permission.WORKFLOW_CREATE,
            Permission.WORKFLOW_CANCEL,
            Permission.POLICY_EVALUATE,
            Permission.APPROVAL_REQUEST,
            Permission.FAILURE_LAB_RUN,
        }
    ),
    Role.REVIEWER: frozenset(
        _STAFF_READ
        | {
            Permission.WORKFLOW_CREATE,
            Permission.WORKFLOW_CANCEL,
            Permission.WORKFLOW_RESUME,
            Permission.POLICY_EVALUATE,
            Permission.APPROVAL_REQUEST,
            Permission.APPROVAL_DECIDE_STANDARD,
            Permission.SECURITY_READ,
            Permission.FAILURE_LAB_RUN,
        }
    ),
    Role.SENIOR_REVIEWER: frozenset(
        _STAFF_READ
        | {
            Permission.WORKFLOW_CREATE,
            Permission.WORKFLOW_CANCEL,
            Permission.WORKFLOW_RESUME,
            Permission.POLICY_EVALUATE,
            Permission.APPROVAL_REQUEST,
            Permission.APPROVAL_DECIDE_STANDARD,
            Permission.APPROVAL_DECIDE_SENIOR,
            Permission.SECURITY_READ,
            Permission.FAILURE_LAB_RUN,
        }
    ),
    Role.ADMINISTRATOR: frozenset(
        _STAFF_READ
        | {
            Permission.WORKFLOW_CREATE,
            Permission.WORKFLOW_CANCEL,
            Permission.WORKFLOW_RESUME,
            Permission.CUSTOMER_UPDATE,
            Permission.POLICY_EVALUATE,
            Permission.POLICY_MANAGE,
            Permission.APPROVAL_REQUEST,
            Permission.APPROVAL_DECIDE_STANDARD,
            Permission.APPROVAL_DECIDE_SENIOR,
            Permission.SECURITY_READ,
            Permission.FAILURE_LAB_RUN,
            Permission.ADMIN_FAILURE_INJECTION,
            Permission.ADMIN_SEED,
        }
    ),
    # Least privilege for the agent: it may read, evaluate policy, ask for approval and
    # execute a refund *only* through the tool registry, which additionally checks the
    # workflow state and the approval binding. It can never approve, never update
    # customer records and never manage policy.
    Role.AGENT: frozenset(
        {
            Permission.WORKFLOW_READ,
            Permission.CUSTOMER_READ,
            Permission.ORDER_READ,
            Permission.POLICY_READ,
            Permission.POLICY_EVALUATE,
            Permission.APPROVAL_REQUEST,
            Permission.APPROVAL_READ,
            Permission.REFUND_EXECUTE,
        }
    ),
}


def has_permission(role: Role | str, permission: Permission | str) -> bool:
    try:
        role_enum = Role(role)
        perm_enum = Permission(permission)
    except ValueError:
        return False
    return perm_enum in PERMISSION_MATRIX[role_enum]


def role_rank(role: Role) -> int:
    """Rank used to compare reviewer seniority for approvals."""
    return {
        Role.AGENT: 0,
        Role.SUPPORT_OPERATOR: 1,
        Role.REVIEWER: 2,
        Role.SENIOR_REVIEWER: 3,
        Role.ADMINISTRATOR: 4,
    }[role]


def decision_permission_for(required_role: Role) -> Permission:
    if required_role == Role.SENIOR_REVIEWER:
        return Permission.APPROVAL_DECIDE_SENIOR
    return Permission.APPROVAL_DECIDE_STANDARD


PrincipalType = Literal["user", "agent", "system"]


@dataclass(frozen=True)
class Principal:
    """Who is performing an action. Users come from JWTs; the agent and system are fixed."""

    id: str
    type: PrincipalType
    role: Role
    display_name: str

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)


AGENT_PRINCIPAL = Principal(
    id="agent:refund-agent", type="agent", role=Role.AGENT, display_name="Refund Agent"
)
SYSTEM_PRINCIPAL = Principal(
    id="system", type="system", role=Role.ADMINISTRATOR, display_name="System"
)


def permission_matrix_table() -> list[dict[str, object]]:
    """Serialisable permission matrix for the architecture API and docs."""
    roles = list(Role)
    return [
        {
            "permission": perm.value,
            "roles": {role.value: perm in PERMISSION_MATRIX[role] for role in roles},
        }
        for perm in Permission
    ]
