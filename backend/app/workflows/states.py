"""Workflow state machine definition.

The transition table below is the *single source of truth* for which state changes are
legal. ``WorkflowService.transition`` refuses anything not listed here, and the
Architecture Explorer renders this table live, so the diagram can never drift from the
implementation.
"""

from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    VERIFYING = "VERIFYING"
    POLICY_CHECK = "POLICY_CHECK"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Allowed transitions: current state -> set of next states.
TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.CREATED: frozenset(
        {WorkflowState.ANALYZING, WorkflowState.CANCELLED, WorkflowState.FAILED}
    ),
    WorkflowState.ANALYZING: frozenset(
        {WorkflowState.VERIFYING, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.VERIFYING: frozenset(
        {
            WorkflowState.POLICY_CHECK,
            WorkflowState.REJECTED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.POLICY_CHECK: frozenset(
        {
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.APPROVED,
            WorkflowState.REJECTED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.AWAITING_APPROVAL: frozenset(
        {WorkflowState.APPROVED, WorkflowState.REJECTED, WorkflowState.CANCELLED}
    ),
    WorkflowState.APPROVED: frozenset(
        {WorkflowState.EXECUTING, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.EXECUTING: frozenset({WorkflowState.COMPLETED, WorkflowState.FAILED}),
    # FAILED is recoverable: a resume re-enters the step recorded in the checkpoint.
    WorkflowState.FAILED: frozenset(
        {
            WorkflowState.ANALYZING,
            WorkflowState.VERIFYING,
            WorkflowState.POLICY_CHECK,
            WorkflowState.EXECUTING,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.REJECTED: frozenset(),
    WorkflowState.CANCELLED: frozenset(),
}

TERMINAL_STATES: frozenset[WorkflowState] = frozenset(
    {WorkflowState.COMPLETED, WorkflowState.REJECTED, WorkflowState.CANCELLED}
)

# States in which the orchestrator is (or should be) actively working. A workflow found
# in one of these states after a restart was interrupted and can be resumed.
IN_FLIGHT_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.CREATED,
        WorkflowState.ANALYZING,
        WorkflowState.VERIFYING,
        WorkflowState.POLICY_CHECK,
        WorkflowState.APPROVED,
        WorkflowState.EXECUTING,
    }
)

WAITING_STATES: frozenset[WorkflowState] = frozenset({WorkflowState.AWAITING_APPROVAL})

CANCELLABLE_STATES: frozenset[WorkflowState] = frozenset(
    state for state, nxt in TRANSITIONS.items() if WorkflowState.CANCELLED in nxt
)

# The "happy path" order used for display purposes only.
HAPPY_PATH: tuple[WorkflowState, ...] = (
    WorkflowState.CREATED,
    WorkflowState.ANALYZING,
    WorkflowState.VERIFYING,
    WorkflowState.POLICY_CHECK,
    WorkflowState.AWAITING_APPROVAL,
    WorkflowState.APPROVED,
    WorkflowState.EXECUTING,
    WorkflowState.COMPLETED,
)


def can_transition(current: WorkflowState, target: WorkflowState) -> bool:
    return target in TRANSITIONS[current]


def transition_table() -> list[dict[str, object]]:
    """Serialisable view of the transition table (used by the architecture API)."""
    return [
        {
            "from": state.value,
            "to": sorted(s.value for s in targets),
            "terminal": state in TERMINAL_STATES,
            "in_flight": state in IN_FLIGHT_STATES,
            "waiting": state in WAITING_STATES,
        }
        for state, targets in TRANSITIONS.items()
    ]
