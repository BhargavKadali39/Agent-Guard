"""Workflow orchestrator: an explicit, checkpointed state machine around the agent.

Design (see ARCHITECTURE.md, "Why not LangGraph for v1"):

* Each workflow state has one step function. A step does its work through the tool
  registry, records a checkpoint, performs a *validated* transition and commits.
* Because every step commits, a crash between steps loses nothing: ``resume`` simply
  re-enters the state the workflow is in, and side effects are idempotent.
* The LLM is consulted exactly once (ANALYZING) to interpret the untrusted message. Its
  output is validated against the database (VERIFYING), checked by the deterministic
  policy engine (POLICY_CHECK), gated by human approval when required, and executed
  through an idempotent tool (EXECUTING). The model never authorizes anything.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.factory import apply_provider_fault
from app.agents.provider import AIProvider
from app.agents.scanner import scanner
from app.agents.schemas import (
    AgentInterpretation,
    CandidateOrder,
    InterpretationRequest,
    ToolDescriptor,
)
from app.approvals.service import ApprovalService
from app.auth.permissions import AGENT_PRINCIPAL, SYSTEM_PRINCIPAL, Principal, Role
from app.config import Settings
from app.database import utcnow
from app.errors import (
    AgentGuardError,
    ConcurrentUpdateError,
    ConflictError,
    InvalidTransition,
    ProviderError,
    SimulatedInterruption,
    ToolAuthorizationError,
    ToolExecutionError,
    ValidationFailed,
    WorkflowBusyError,
)
from app.evaluations.failure_injection import FailureInjector, SimulationConfig
from app.models import (
    ApprovalReason,
    ApprovalStatus,
    AuthorizationOutcome,
    EventCategory,
    OrderStatus,
    Severity,
    Workflow,
)
from app.observability.audit import AuditLogger
from app.policies.service import PolicyService
from app.services.business import (
    CustomerService,
    OrderService,
    RefundService,
    SimulatedPaymentGateway,
)
from app.tools.registry import ToolContext, ToolRegistry
from app.workflows.service import WorkflowService
from app.workflows.states import IN_FLIGHT_STATES, TERMINAL_STATES, WorkflowState

logger = logging.getLogger(__name__)

REVIEW_REASON_PRIORITY = (
    ApprovalReason.AGENT_DISCREPANCY,
    ApprovalReason.LOW_CONFIDENCE,
    ApprovalReason.SUSPICIOUS_CONTENT,
)


class WorkflowOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings,
        provider: AIProvider,
        registry: ToolRegistry,
        injector: FailureInjector,
        gateway: SimulatedPaymentGateway | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.provider = provider
        self.registry = registry
        self.injector = injector
        self.gateway = gateway or SimulatedPaymentGateway(
            injector, latency_ms=settings.simulated_gateway_latency_ms
        )
        self.audit = AuditLogger(db)
        self.workflows = WorkflowService(db, self.audit)
        self.approvals = ApprovalService(
            db, self.audit, expiry_hours=settings.approval_expiry_hours
        )
        self.refunds = RefundService(db, self.gateway, injector)
        self.policies = PolicyService(db)
        self.customers = CustomerService(db)
        self.orders = OrderService(db)
        self._steps: dict[WorkflowState, Callable[[Workflow], None]] = {
            WorkflowState.CREATED: self._step_created,
            WorkflowState.ANALYZING: self._step_analyzing,
            WorkflowState.VERIFYING: self._step_verifying,
            WorkflowState.POLICY_CHECK: self._step_policy_check,
            WorkflowState.APPROVED: self._step_approved,
            WorkflowState.EXECUTING: self._step_executing,
        }

    # ------------------------------------------------------------------ public API
    def submit(
        self,
        *,
        customer_id: str,
        message: str,
        actor: Principal,
        client_request_id: str | None = None,
        simulation: dict[str, Any] | None = None,
    ) -> tuple[Workflow, bool]:
        """Create a workflow and run it until it waits, finishes or fails.

        Returns ``(workflow, created)``. A repeated ``client_request_id`` returns the
        existing workflow instead of creating a duplicate (idempotent submission).
        """
        if client_request_id:
            existing = self.workflows.find_by_client_request_id(client_request_id)
            if existing is not None:
                self.audit.record(
                    category=EventCategory.WORKFLOW,
                    event_type="workflow.duplicate_submission_ignored",
                    message="Duplicate submission matched an existing workflow by "
                    "client_request_id",
                    actor=actor,
                    workflow_id=existing.id,
                    workflow_state=existing.state,
                    payload={"client_request_id": client_request_id},
                )
                self.db.commit()
                return self.workflows.get(existing.id), False
        sim = SimulationConfig.model_validate(simulation or {})
        try:
            workflow = self.workflows.create(
                customer_id=customer_id,
                message=message,
                actor=actor,
                client_request_id=client_request_id,
                simulation=None if sim.is_empty() else sim.model_dump(),
                provider_name=self.provider.name,
            )
            self.db.commit()
        except IntegrityError:
            # Two identical submissions raced; the unique client_request_id let one win.
            self.db.rollback()
            existing = (
                self.workflows.find_by_client_request_id(client_request_id)
                if client_request_id
                else None
            )
            if existing is None:
                raise
            return self.workflows.get(existing.id), False
        return self.run(workflow.id), True

    def run(self, workflow_id: str) -> Workflow:
        """Advance the workflow until it reaches a waiting, terminal or failed state.

        Only the holder of the workflow's processing lease advances it. If another worker
        holds the lease, the current state is returned unchanged.
        """
        token = self._new_lease_token()
        if not self.workflows.claim(
            workflow_id, token=token, ttl_seconds=self.settings.workflow_lease_seconds
        ):
            self.audit.record(
                category=EventCategory.WORKFLOW,
                event_type="workflow.claim_skipped",
                message="Another worker is processing this workflow; not advancing it here",
                actor=SYSTEM_PRINCIPAL,
                workflow_id=workflow_id,
            )
            self.db.commit()
            return self.workflows.get(workflow_id)
        try:
            return self._advance(workflow_id)
        finally:
            self._release(workflow_id, token)

    @staticmethod
    def _new_lease_token() -> str:
        return uuid.uuid4().hex

    def _release(self, workflow_id: str, token: str) -> None:
        try:
            self.workflows.release(workflow_id, token=token)
        except Exception:  # pragma: no cover - the lease also expires on its own
            self.db.rollback()
            logger.exception("could not release lease for workflow %s", workflow_id)

    def _advance(self, workflow_id: str) -> Workflow:
        workflow = self.workflows.get(workflow_id)
        while True:
            state = WorkflowState(workflow.state)
            step = self._steps.get(state)
            if step is None:
                break
            try:
                step(workflow)
            except SimulatedInterruption as exc:
                self._record_interruption(workflow, exc)
                raise
            except ConcurrentUpdateError as exc:
                self._record_concurrent_update(workflow_id, exc)
                break
            except (ToolExecutionError, ProviderError) as exc:
                self._fail(workflow, exc, resumable=True)
                break
            except ToolAuthorizationError as exc:
                self._fail(workflow, exc, resumable=False)
                break
            except (InvalidTransition, ConflictError, ValidationFailed) as exc:
                self._fail(workflow, exc, resumable=False)
                break
            except AgentGuardError as exc:
                self._fail(workflow, exc, resumable=True)
                break
            except Exception as exc:  # unexpected bug: never leave the workflow dangling
                logger.exception("unexpected orchestrator failure in %s", state.value)
                self.db.rollback()
                self._fail(workflow, exc, resumable=True, unexpected=True)
                break
            workflow = self.workflows.get(workflow_id)
        return self.workflows.get(workflow_id)

    def resume(self, workflow_id: str, *, actor: Principal) -> Workflow:
        workflow = self.workflows.get(workflow_id)
        if WorkflowState(workflow.state) in TERMINAL_STATES:
            return self._resume_noop(workflow, actor)
        if WorkflowState(workflow.state) not in IN_FLIGHT_STATES | {WorkflowState.FAILED}:
            raise InvalidTransition(
                f"workflow in state {workflow.state} is waiting for a human and cannot be resumed",
                details={"state": workflow.state},
            )
        token = self._new_lease_token()
        if not self.workflows.claim(
            workflow_id, token=token, ttl_seconds=self.settings.workflow_lease_seconds
        ):
            raise WorkflowBusyError(
                "workflow is already being processed by another worker",
                details={"state": workflow.state},
            )
        try:
            # Re-read under the lease: the previous holder may have moved it on.
            workflow = self.workflows.get(workflow_id)
            state = WorkflowState(workflow.state)
            if state in TERMINAL_STATES:
                return self._resume_noop(workflow, actor)
            if state == WorkflowState.FAILED:
                if not workflow.resumable:
                    raise InvalidTransition(
                        "workflow failed with a non-recoverable error and cannot be resumed",
                        details={"failure_reason": workflow.failure_reason},
                    )
                checkpoint = workflow.checkpoint or {}
                target = WorkflowState(checkpoint.get("resume_target") or WorkflowState.ANALYZING)
                self.workflows.transition(
                    workflow,
                    target,
                    actor=actor,
                    reason="resumed from failure",
                    payload={"resume_count": workflow.resume_count + 1},
                )
            elif state in IN_FLIGHT_STATES:
                self.audit.record(
                    category=EventCategory.WORKFLOW,
                    event_type="workflow.resumed",
                    message=f"Resuming interrupted workflow from state {state.value}",
                    actor=actor,
                    workflow_id=workflow.id,
                    workflow_state=workflow.state,
                    payload={"checkpoint": workflow.checkpoint},
                )
            else:
                raise InvalidTransition(
                    f"workflow in state {state.value} is waiting for a human and cannot be resumed",
                    details={"state": state.value},
                )
            workflow.resume_count += 1
            self.db.add(workflow)
            self.db.commit()
            return self._advance(workflow.id)
        except ConcurrentUpdateError:
            self.db.rollback()
            raise
        finally:
            self._release(workflow_id, token)

    def _resume_noop(self, workflow: Workflow, actor: Principal) -> Workflow:
        # Idempotent: resuming a finished workflow changes nothing, but is auditable.
        self.audit.record(
            category=EventCategory.WORKFLOW,
            event_type="workflow.resume_noop",
            message=f"Resume requested for terminal workflow ({workflow.state}); nothing to do",
            actor=actor,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
        )
        self.db.commit()
        return workflow

    def recover_in_flight(self) -> list[str]:
        """Called at startup: resume every workflow a previous process left mid-flight."""
        recovered: list[str] = []
        for workflow in self.workflows.in_flight():
            try:
                self.audit.record(
                    category=EventCategory.SYSTEM,
                    event_type="workflow.recovered",
                    message="Workflow found in-flight at startup; attempting to resume it",
                    actor=SYSTEM_PRINCIPAL,
                    workflow_id=workflow.id,
                    workflow_state=workflow.state,
                )
                self.db.commit()
                self.resume(workflow.id, actor=SYSTEM_PRINCIPAL)
                recovered.append(workflow.id)
            except SimulatedInterruption:
                recovered.append(workflow.id)
            except AgentGuardError as exc:
                logger.warning("could not recover workflow %s: %s", workflow.id, exc.message)
        return recovered

    def cancel(self, workflow_id: str, *, actor: Principal, reason: str) -> Workflow:
        workflow = self.workflows.get(workflow_id)
        self.approvals.invalidate_pending(
            workflow, reason=f"workflow cancelled: {reason}", actor=actor
        )
        self.workflows.cancel(workflow, actor=actor, reason=reason)
        self.db.commit()
        return self.workflows.get(workflow_id)

    def decide_approval(
        self, approval_id: str, *, decision: str, reviewer: Principal, comment: str | None
    ) -> Workflow:
        try:
            return self._decide_approval(
                approval_id, decision=decision, reviewer=reviewer, comment=comment
            )
        except ConcurrentUpdateError:
            self.db.rollback()
            raise

    def _decide_approval(
        self, approval_id: str, *, decision: str, reviewer: Principal, comment: str | None
    ) -> Workflow:
        approval = self.approvals.decide(
            approval_id, decision=decision, reviewer=reviewer, comment=comment
        )
        workflow = self.workflows.get(approval.workflow_id)
        if approval.status == ApprovalStatus.APPROVED:
            workflow.approval_id = approval.id
            self.workflows.transition(
                workflow,
                WorkflowState.APPROVED,
                actor=reviewer,
                reason=f"approved by {reviewer.display_name}",
                payload={"approval_id": approval.id},
            )
            self.workflows.checkpoint(workflow, "approved", approval_id=approval.id)
            self.db.commit()
            return self.run(workflow.id)
        self.workflows.transition(
            workflow,
            WorkflowState.REJECTED,
            actor=reviewer,
            reason=f"rejected_by_reviewer: {comment or 'no comment'}",
            payload={"approval_id": approval.id},
        )
        self.db.commit()
        return self.workflows.get(workflow.id)

    # --------------------------------------------------------------------- steps
    def _ctx(self, workflow: Workflow, principal: Principal = AGENT_PRINCIPAL) -> ToolContext:
        return ToolContext(
            db=self.db,
            principal=principal,
            audit=self.audit,
            injector=self.injector,
            settings=self.settings,
            policy_engine=self.policies.engine(),
            approval_service=self.approvals,
            refund_service=self.refunds,
            workflow=workflow,
        )

    def _step_created(self, workflow: Workflow) -> None:
        self.workflows.transition(workflow, WorkflowState.ANALYZING, actor=AGENT_PRINCIPAL)
        self.db.commit()
        self.injector.maybe_interrupt(self.db, workflow, WorkflowState.CREATED.value)

    def _step_analyzing(self, workflow: Workflow) -> None:
        customer = self.customers.get(workflow.customer_id)
        candidate_orders = [
            CandidateOrder(
                order_id=o.id,
                product_name=o.product.name,
                total_paise=o.total_paise,
                refunded_paise=o.refunded_paise,
                status=o.status,
                delivered_at=o.delivered_at.isoformat() if o.delivered_at else None,
            )
            for o in self.orders.list_for_customer(customer.id)[:10]
        ]

        # Untrusted-content scan: a detector that escalates, not a security boundary.
        scan = scanner.scan(workflow.message)
        if scan.suspicious:
            self.audit.record(
                category=EventCategory.SECURITY,
                event_type="security.injection_suspected",
                severity=Severity.WARNING,
                message="Customer message contains instruction-like text; treated as data only",
                actor=AGENT_PRINCIPAL,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                payload={"patterns": scan.matched_patterns, "excerpts": scan.excerpts},
            )

        request = InterpretationRequest(
            workflow_id=workflow.id,
            customer_id=customer.id,
            customer_name=customer.name,
            candidate_orders=candidate_orders,
            untrusted_message=workflow.message,
            tools=[
                ToolDescriptor(
                    name=d["name"], description=d["description"], parameters=d["input_schema"]
                )
                for d in self.registry.descriptors()
            ],
        )
        interpretation = self.provider.interpret(request)
        fault = self.injector.provider_fault(workflow)
        if fault:
            interpretation = apply_provider_fault(interpretation, fault)
            self.audit.record(
                category=EventCategory.EVALUATION,
                event_type="agent.fault_injected",
                severity=Severity.WARNING,
                message=f"Simulated agent decision error injected: {fault}",
                actor=SYSTEM_PRINCIPAL,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                payload={"fault": fault},
            )
        if scan.suspicious and not interpretation.suspected_injection:
            interpretation = interpretation.model_copy(update={"suspected_injection": True})

        workflow.interpretation = interpretation.model_dump(mode="json")
        self.audit.record(
            category=EventCategory.AGENT,
            event_type="agent.interpretation_completed",
            message=f"Agent interpretation: {interpretation.summary}",
            actor=AGENT_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            duration_ms=interpretation.latency_ms,
            payload={
                "provider": interpretation.provider,
                "model": interpretation.model,
                "intent": interpretation.intent,
                "order_id": interpretation.order_id,
                "requested_amount_paise": interpretation.requested_amount_paise,
                "confidence": interpretation.confidence,
                "suspected_injection": interpretation.suspected_injection,
                "proposed_tool_calls": [p.tool for p in interpretation.proposed_tool_calls],
            },
        )
        self.workflows.checkpoint(
            workflow, "interpreted", scan_patterns=scan.matched_patterns, provider_fault=fault
        )

        # Every tool the agent *proposes* goes through the same authorization gate as the
        # pipeline's own calls. Reads in scope succeed; anything else is denied and logged.
        allowed, denied = self._process_proposals(workflow, interpretation)
        self.audit.record(
            category=EventCategory.AGENT,
            event_type="agent.proposals_processed",
            severity=Severity.WARNING if denied else Severity.INFO,
            message=f"Agent proposed {len(interpretation.proposed_tool_calls)} tool call(s): "
            f"{len(allowed)} allowed, {len(denied)} denied",
            actor=AGENT_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload={"allowed": allowed, "denied": denied},
        )
        self.workflows.transition(workflow, WorkflowState.VERIFYING, actor=AGENT_PRINCIPAL)
        self.db.commit()
        self.injector.maybe_interrupt(self.db, workflow, WorkflowState.ANALYZING.value)

    def _process_proposals(
        self, workflow: Workflow, interpretation: AgentInterpretation
    ) -> tuple[list[str], list[dict[str, str]]]:
        allowed: list[str] = []
        denied: list[dict[str, str]] = []
        ctx = self._ctx(workflow)
        for proposal in interpretation.proposed_tool_calls[: self.settings.max_proposed_tool_calls]:
            try:
                self.registry.execute(proposal.tool, proposal.arguments, ctx)
                allowed.append(proposal.tool)
            except ToolAuthorizationError as exc:
                denied.append({"tool": proposal.tool, "reason": exc.message})
            except ValidationFailed as exc:
                denied.append(
                    {"tool": proposal.tool, "reason": f"invalid arguments: {exc.message}"}
                )
            except ToolExecutionError as exc:
                denied.append({"tool": proposal.tool, "reason": f"failed: {exc.message}"})
            except AgentGuardError as exc:
                denied.append({"tool": proposal.tool, "reason": exc.message})
        return allowed, denied

    def _step_verifying(self, workflow: Workflow) -> None:
        interpretation = AgentInterpretation.model_validate(workflow.interpretation or {})
        ctx = self._ctx(workflow)
        flags: list[str] = []
        discrepancies: list[str] = []

        if interpretation.intent != "refund_request":
            discrepancies.append(f"intent_not_refund:{interpretation.intent}")

        # ---- resolve the order from trusted data ---------------------------------
        order = None
        if interpretation.order_id:
            order = self.orders.get_for_customer(interpretation.order_id, workflow.customer_id)
            if order is None:
                discrepancies.append(f"order_not_found_or_not_owned:{interpretation.order_id}")
        if order is None:
            candidates = [
                o
                for o in self.orders.list_for_customer(workflow.customer_id)
                if o.status == OrderStatus.DELIVERED and o.refundable_paise > 0
            ]
            if len(candidates) == 1:
                order = candidates[0]
                flags.append("order_inferred_from_customer_history")
            elif len(candidates) > 1:
                discrepancies.append("order_ambiguous")

        if order is None:
            verification = {
                "order_id": None,
                "amount_paise": None,
                "requested_amount_paise": interpretation.requested_amount_paise,
                "refundable_paise": None,
                "flags": flags,
                "discrepancies": discrepancies,
                "requires_human_review": False,
                "review_reason": None,
                "verified_at": utcnow().isoformat(),
            }
            workflow.verification = verification
            self.workflows.checkpoint(workflow, "verification_failed")
            self.audit.record(
                category=EventCategory.EVALUATION,
                event_type="evaluation.verification_failed",
                severity=Severity.WARNING,
                message="Could not identify a refundable order for this customer",
                actor=AGENT_PRINCIPAL,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                payload=verification,
            )
            self.workflows.transition(
                workflow,
                WorkflowState.REJECTED,
                actor=AGENT_PRINCIPAL,
                reason="order_not_identified: " + (", ".join(discrepancies) or "no eligible order"),
            )
            self.db.commit()
            return

        workflow.order_id = order.id
        self.db.add(workflow)
        self.db.flush()
        # Fetch through the tool layer so the audit trail shows the agent's reads.
        self.registry.execute("get_customer_details", {"customer_id": workflow.customer_id}, ctx)
        order_info = self.registry.execute("get_order_information", {"order_id": order.id}, ctx)
        refundable = int(order_info.output["refundable_paise"])

        # ---- reconcile the amount against trusted facts --------------------------
        requested = interpretation.requested_amount_paise
        if requested is None or requested == 0:
            amount = refundable
            flags.append("amount_defaulted_to_refundable_balance")
        elif requested > refundable:
            discrepancies.append(f"amount_exceeds_refundable:{requested}>{refundable}")
            amount = refundable
        else:
            amount = requested

        if interpretation.confidence < self.settings.low_confidence_threshold:
            flags.append("low_confidence")
        if interpretation.conflicting_statements:
            discrepancies.append("conflicting_statements")
        if interpretation.suspected_injection:
            flags.append("suspicious_content")

        review_reason: str | None = None
        if discrepancies:
            review_reason = ApprovalReason.AGENT_DISCREPANCY.value
        elif "low_confidence" in flags:
            review_reason = ApprovalReason.LOW_CONFIDENCE.value
        elif "suspicious_content" in flags and self.settings.force_review_on_injection:
            review_reason = ApprovalReason.SUSPICIOUS_CONTENT.value

        verification = {
            "order_id": order.id,
            "amount_paise": amount,
            "requested_amount_paise": requested,
            "refundable_paise": refundable,
            "flags": flags,
            "discrepancies": discrepancies,
            "requires_human_review": review_reason is not None,
            "review_reason": review_reason,
            "verified_at": utcnow().isoformat(),
        }
        workflow.verification = verification
        self.workflows.checkpoint(workflow, "verified", order_id=order.id, amount_paise=amount)
        self.audit.record(
            category=EventCategory.EVALUATION,
            event_type="evaluation.discrepancy_detected"
            if discrepancies
            else "evaluation.verification_completed",
            severity=Severity.WARNING if discrepancies else Severity.INFO,
            message=(
                "Agent interpretation disagrees with trusted data: " + ", ".join(discrepancies)
                if discrepancies
                else f"Verified order {order.id}; proposed refund ₹{amount / 100:,.2f}"
            ),
            actor=AGENT_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload=verification,
        )
        self.workflows.transition(workflow, WorkflowState.POLICY_CHECK, actor=AGENT_PRINCIPAL)
        self.db.commit()
        self.injector.maybe_interrupt(self.db, workflow, WorkflowState.VERIFYING.value)

    def _step_policy_check(self, workflow: Workflow) -> None:
        verification = workflow.verification or {}
        amount = int(verification["amount_paise"])
        order_id = str(verification["order_id"])
        ctx = self._ctx(workflow)

        self.registry.execute("retrieve_refund_policy", {}, ctx)
        decision = self.registry.execute(
            "evaluate_refund_eligibility", {"order_id": order_id, "amount_paise": amount}, ctx
        ).output
        workflow.policy_decision = decision
        self.audit.record(
            category=EventCategory.POLICY,
            event_type="policy.evaluated",
            severity=Severity.INFO if decision["eligible"] else Severity.WARNING,
            message=(
                f"Policy {decision['policy_name']} v{decision['policy_version']}: "
                + ("eligible, tier " + decision["tier"] if decision["eligible"] else "not eligible")
                + f" ({', '.join(decision['reasons'])})"
            ),
            actor=AGENT_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload=decision,
        )
        self.workflows.checkpoint(workflow, "policy_evaluated")

        if not decision["eligible"]:
            if decision["exception_override_available"]:
                approval = self.registry.execute(
                    "create_approval_request",
                    {
                        "amount_paise": amount,
                        "required_role": Role.SENIOR_REVIEWER.value,
                        "reason": ApprovalReason.POLICY_EXCEPTION.value,
                        "details": {"policy_reasons": decision["reasons"]},
                    },
                    ctx,
                ).output
                workflow.approval_id = approval["approval_id"]
                self.workflows.transition(
                    workflow,
                    WorkflowState.AWAITING_APPROVAL,
                    actor=AGENT_PRINCIPAL,
                    reason="policy exception requires senior reviewer",
                )
            else:
                self.workflows.transition(
                    workflow,
                    WorkflowState.REJECTED,
                    actor=AGENT_PRINCIPAL,
                    reason="policy:" + ",".join(decision["reasons"]),
                )
            self.db.commit()
            self.injector.maybe_interrupt(self.db, workflow, WorkflowState.POLICY_CHECK.value)
            return

        required_role = decision["required_role"]
        needs_review = bool(verification.get("requires_human_review"))
        if required_role is None and not needs_review:
            approval = self.approvals.auto_approve(workflow=workflow, amount_paise=amount)
            workflow.approval_id = approval.id
            self.workflows.checkpoint(workflow, "approved", approval_id=approval.id)
            self.workflows.transition(
                workflow, WorkflowState.APPROVED, actor=AGENT_PRINCIPAL, reason="auto-approved"
            )
        else:
            role = required_role or Role.REVIEWER.value
            reason = (
                ApprovalReason.POLICY_TIER.value
                if required_role
                else str(verification.get("review_reason") or ApprovalReason.LOW_CONFIDENCE.value)
            )
            approval = self.registry.execute(
                "create_approval_request",
                {
                    "amount_paise": amount,
                    "required_role": role,
                    "reason": reason,
                    "details": {
                        "policy_tier": decision["tier"],
                        "flags": verification.get("flags", []),
                        "discrepancies": verification.get("discrepancies", []),
                        "requested_amount_paise": verification.get("requested_amount_paise"),
                        "agent_summary": (workflow.interpretation or {}).get("summary"),
                        "review_reason": verification.get("review_reason"),
                    },
                },
                ctx,
            ).output
            workflow.approval_id = approval["approval_id"]
            self.workflows.checkpoint(
                workflow, "approval_requested", approval_id=approval["approval_id"]
            )
            self.workflows.transition(
                workflow,
                WorkflowState.AWAITING_APPROVAL,
                actor=AGENT_PRINCIPAL,
                reason=f"{role} approval required ({reason})",
            )
        self.db.commit()
        self.injector.maybe_interrupt(self.db, workflow, WorkflowState.POLICY_CHECK.value)

    def _step_approved(self, workflow: Workflow) -> None:
        self.workflows.transition(workflow, WorkflowState.EXECUTING, actor=AGENT_PRINCIPAL)
        self.db.commit()
        self.injector.maybe_interrupt(self.db, workflow, WorkflowState.APPROVED.value)

    def _step_executing(self, workflow: Workflow) -> None:
        if not workflow.approval_id:
            raise ValidationFailed("workflow reached EXECUTING without an approval")
        approval = self.approvals.get(workflow.approval_id)
        ctx = self._ctx(workflow)
        result = self.registry.execute(
            "execute_simulated_refund",
            {
                "order_id": workflow.order_id,
                "amount_paise": approval.amount_paise,
                "approval_id": approval.id,
            },
            ctx,
        ).output
        self.workflows.checkpoint(
            workflow, "execution_recorded", execution_id=result["execution_id"]
        )
        self.db.commit()
        # Crash window between "money moved" and "workflow marked complete".
        self.injector.maybe_interrupt(self.db, workflow, "EXECUTION_COMMIT")
        self.audit.record(
            category=EventCategory.EXECUTION,
            event_type="execution.completed" if result["created"] else "execution.replayed",
            message=(
                f"Simulated refund of ₹{result['amount_paise'] / 100:,.2f} executed "
                f"({result['gateway_reference']})"
                if result["created"]
                else "Refund already executed; idempotent replay returned the original result"
            ),
            actor=AGENT_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload=result,
        )
        self.workflows.transition(workflow, WorkflowState.COMPLETED, actor=AGENT_PRINCIPAL)
        self.db.commit()

    # ---------------------------------------------------------------- failures
    def _record_interruption(self, workflow: Workflow, exc: SimulatedInterruption) -> None:
        exc.details.setdefault("workflow_id", workflow.id)
        self.audit.record(
            category=EventCategory.SYSTEM,
            event_type="workflow.interrupted",
            severity=Severity.ERROR,
            message=f"Process interrupted: {exc.message}. State and checkpoint are persisted.",
            actor=SYSTEM_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload={"checkpoint": workflow.checkpoint, **exc.details},
        )
        self.db.commit()

    def _record_concurrent_update(self, workflow_id: str, exc: ConcurrentUpdateError) -> None:
        self.db.rollback()
        current = self.workflows.get(workflow_id)
        self.audit.record(
            category=EventCategory.WORKFLOW,
            event_type="workflow.concurrent_update_detected",
            severity=Severity.WARNING,
            message=f"State changed underneath this worker ({exc.message}); "
            f"stopping without overwriting it (now {current.state})",
            actor=SYSTEM_PRINCIPAL,
            workflow_id=workflow_id,
            workflow_state=current.state,
            payload=exc.details,
        )
        self.db.commit()

    def _fail(
        self, workflow: Workflow, exc: Exception, *, resumable: bool, unexpected: bool = False
    ) -> None:
        workflow = self.workflows.get(workflow.id)
        if WorkflowState(workflow.state) in TERMINAL_STATES | {WorkflowState.FAILED}:
            self.db.commit()
            return
        reason = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
        if unexpected:
            reason = f"unexpected error: {reason}"
        self.audit.record(
            category=EventCategory.WORKFLOW,
            event_type="workflow.failure_encountered",
            severity=Severity.ERROR,
            message=f"Step {workflow.state} failed: {reason}",
            actor=SYSTEM_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            authorization_outcome=AuthorizationOutcome.DENIED
            if isinstance(exc, ToolAuthorizationError)
            else AuthorizationOutcome.NOT_APPLICABLE,
            payload={"resumable": resumable, "error_type": type(exc).__name__},
        )
        try:
            self.workflows.mark_failed(
                workflow, reason=reason, resumable=resumable, actor=SYSTEM_PRINCIPAL
            )
        except ConcurrentUpdateError as conflict:
            self._record_concurrent_update(workflow.id, conflict)
            return
        self.db.commit()
