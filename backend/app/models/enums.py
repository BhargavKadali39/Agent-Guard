"""Small enumerations persisted as strings."""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ApprovalReason(StrEnum):
    AUTO_APPROVAL = "auto_approval"
    POLICY_TIER = "policy_tier"
    POLICY_EXCEPTION = "policy_exception"
    AGENT_DISCREPANCY = "agent_discrepancy"
    LOW_CONFIDENCE = "low_confidence"
    SUSPICIOUS_CONTENT = "suspicious_content"


class EventCategory(StrEnum):
    WORKFLOW = "workflow"
    AGENT = "agent"
    TOOL = "tool"
    POLICY = "policy"
    APPROVAL = "approval"
    EXECUTION = "execution"
    SECURITY = "security"
    EVALUATION = "evaluation"
    SYSTEM = "system"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AuthorizationOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    NOT_APPLICABLE = "n/a"


class RefundTier(StrEnum):
    AUTO = "auto"
    REVIEWER = "reviewer"
    SENIOR_REVIEWER = "senior_reviewer"
    REJECTED = "rejected"
