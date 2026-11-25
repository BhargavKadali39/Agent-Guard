"""Domain exceptions. The API layer maps these to HTTP status codes in one place."""

from __future__ import annotations


class AgentGuardError(Exception):
    """Base class for all domain errors."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.details = details or {}


class NotFoundError(AgentGuardError):
    status_code = 404
    code = "not_found"


class ConflictError(AgentGuardError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AgentGuardError):
    status_code = 422
    code = "validation_failed"


class AuthenticationError(AgentGuardError):
    status_code = 401
    code = "authentication_required"


class PermissionDenied(AgentGuardError):
    status_code = 403
    code = "permission_denied"


class InvalidTransition(ConflictError):
    code = "invalid_transition"


class ConcurrentUpdateError(ConflictError):
    """A compare-and-swap update lost a race: someone else changed the record first."""

    code = "concurrent_update"


class WorkflowBusyError(ConflictError):
    """Another worker currently holds the workflow's processing lease."""

    code = "workflow_busy"


class ToolAuthorizationError(PermissionDenied):
    """A tool call was refused by the registry's authorization gate."""

    code = "tool_authorization_denied"


class ToolExecutionError(AgentGuardError):
    """A tool failed. ``retryable`` tells the registry whether another attempt is safe."""

    status_code = 502
    code = "tool_execution_failed"

    def __init__(self, message: str, *, retryable: bool = False, details: dict | None = None):
        super().__init__(message, details=details)
        self.retryable = retryable


class TransientToolError(ToolExecutionError):
    code = "tool_transient_failure"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message, retryable=True, details=details)


class SimulatedInterruption(AgentGuardError):
    """Raised by the failure-injection mechanism to emulate a crash mid-workflow."""

    status_code = 503
    code = "simulated_interruption"


class ProviderError(AgentGuardError):
    """The AI provider could not produce a usable interpretation."""

    status_code = 502
    code = "ai_provider_error"
