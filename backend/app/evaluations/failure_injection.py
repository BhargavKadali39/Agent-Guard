"""Controlled failure injection for demonstrations and tests.

Two sources of faults are merged:

* **Per-workflow simulation config** stored on ``Workflow.simulation`` (set when a request
  is created, e.g. by the Failure Lab or the Playground's "simulate" options). Counters
  are persisted on the workflow so they survive restarts and resumes.
* **Global injections** held in process memory and managed by administrators through the
  API (useful for live demos: "the payment gateway is now down").

Every injection point consumes its counter *before* raising, and the consumption is
committed immediately so that a resumed workflow does not hit the same injected failure
forever.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.errors import SimulatedInterruption, ToolExecutionError, TransientToolError
from app.models import Workflow

FaultMode = Literal["transient", "permanent"]
ProviderFault = Literal["misread_amount", "wrong_intent", "low_confidence"]


class SimulationConfig(BaseModel):
    """Per-workflow failure simulation settings (all optional)."""

    fail_tool: str | None = None
    fail_times: int = Field(default=0, ge=0, le=20)
    fail_mode: FaultMode = "transient"
    gateway_fail_times: int = Field(default=0, ge=0, le=20)
    db_fail_times: int = Field(default=0, ge=0, le=20)
    interrupt_after: str | None = None  # a WorkflowState name or "EXECUTION_COMMIT"
    interrupt_armed: bool = True
    provider_fault: ProviderFault | None = None
    notes: str | None = None

    def is_empty(self) -> bool:
        return self == SimulationConfig()


class GlobalInjection(BaseModel):
    id: str
    point: str  # e.g. "tool:execute_simulated_refund", "gateway", "db:refund_commit", "provider"
    mode: FaultMode = "transient"
    remaining: int | None = None  # None = until cleared
    description: str = ""
    fired: int = 0


class FailureInjector:
    def __init__(self) -> None:
        self._global: dict[str, GlobalInjection] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ global admin
    def add_global(
        self,
        point: str,
        *,
        mode: FaultMode = "transient",
        times: int | None = None,
        description: str = "",
    ) -> GlobalInjection:
        injection = GlobalInjection(
            id=str(uuid.uuid4()), point=point, mode=mode, remaining=times, description=description
        )
        with self._lock:
            self._global[injection.id] = injection
        return injection

    def clear_global(self, injection_id: str | None = None) -> int:
        with self._lock:
            if injection_id is None:
                count = len(self._global)
                self._global.clear()
                return count
            return 1 if self._global.pop(injection_id, None) else 0

    def list_global(self) -> list[GlobalInjection]:
        with self._lock:
            return [i.model_copy() for i in self._global.values()]

    def _consume_global(self, point: str) -> GlobalInjection | None:
        with self._lock:
            for injection in self._global.values():
                if injection.point != point:
                    continue
                if injection.remaining is not None and injection.remaining <= 0:
                    continue
                if injection.remaining is not None:
                    injection.remaining -= 1
                injection.fired += 1
                return injection.model_copy()
        return None

    # ------------------------------------------------------------- per-workflow state
    @staticmethod
    def config_for(workflow: Workflow | None) -> SimulationConfig:
        if workflow is None or not workflow.simulation:
            return SimulationConfig()
        return SimulationConfig.model_validate(workflow.simulation)

    @staticmethod
    def _save(db: Session, workflow: Workflow, config: SimulationConfig) -> None:
        workflow.simulation = config.model_dump()
        db.add(workflow)
        db.flush()
        db.commit()

    # ---------------------------------------------------------------- check points
    def before_tool(self, db: Session, workflow: Workflow | None, tool_name: str) -> None:
        """Raise an injected error for ``tool_name`` if one is configured."""
        injection = self._consume_global(f"tool:{tool_name}")
        if injection is not None:
            self._raise(injection.mode, f"injected failure for tool {tool_name} (global)")
        cfg = self.config_for(workflow)
        if workflow is not None and cfg.fail_tool == tool_name and cfg.fail_times > 0:
            cfg.fail_times -= 1
            self._save(db, workflow, cfg)
            self._raise(cfg.fail_mode, f"injected failure for tool {tool_name}")

    def before_gateway(self, db: Session, workflow: Workflow | None) -> None:
        injection = self._consume_global("gateway")
        if injection is not None:
            self._raise(injection.mode, "simulated payment gateway timeout (global)")
        cfg = self.config_for(workflow)
        if workflow is not None and cfg.gateway_fail_times > 0:
            cfg.gateway_fail_times -= 1
            self._save(db, workflow, cfg)
            self._raise("transient", "simulated payment gateway timeout")

    def before_db_commit(self, db: Session, workflow: Workflow | None, point: str) -> None:
        injection = self._consume_global(f"db:{point}")
        if injection is not None:
            self._raise(injection.mode, f"simulated database failure at {point} (global)")
        cfg = self.config_for(workflow)
        if workflow is not None and cfg.db_fail_times > 0:
            cfg.db_fail_times -= 1
            self._save(db, workflow, cfg)
            self._raise("transient", f"simulated database failure at {point}")

    def maybe_interrupt(self, db: Session, workflow: Workflow, point: str) -> None:
        """Emulate a process crash right after ``point``; fires once per workflow."""
        cfg = self.config_for(workflow)
        if cfg.interrupt_after == point and cfg.interrupt_armed:
            cfg.interrupt_armed = False
            self._save(db, workflow, cfg)
            raise SimulatedInterruption(
                f"simulated interruption after {point}", details={"point": point}
            )

    def provider_fault(self, workflow: Workflow | None) -> ProviderFault | None:
        injection = self._consume_global("provider")
        if injection is not None:
            return "misread_amount"
        return self.config_for(workflow).provider_fault

    @staticmethod
    def _raise(mode: FaultMode, message: str) -> None:
        if mode == "transient":
            raise TransientToolError(message, details={"injected": True})
        raise ToolExecutionError(message, retryable=False, details={"injected": True})

    def describe(self) -> dict[str, Any]:
        return {
            "global_injections": [i.model_dump() for i in self.list_global()],
            "points": [
                "tool:<tool_name>",
                "gateway",
                "db:refund_commit",
                "provider",
            ],
        }
