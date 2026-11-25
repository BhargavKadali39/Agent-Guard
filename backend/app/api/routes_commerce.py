"""Customers, orders and refund policies."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import DbDep, require
from app.api.serializers import serialize_order
from app.auth.permissions import Permission, Principal
from app.policies.engine import PolicyConfig
from app.policies.service import PolicyService
from app.schemas.api import CustomerOut, OrderOut, PolicyOut
from app.services.business import CustomerService, OrderService

router = APIRouter(prefix="/api", tags=["commerce"])


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    db: DbDep, _: Principal = Depends(require(Permission.CUSTOMER_READ))
) -> list[CustomerOut]:
    return [CustomerOut.model_validate(c) for c in CustomerService(db).list()]


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: str, db: DbDep, _: Principal = Depends(require(Permission.CUSTOMER_READ))
) -> CustomerOut:
    return CustomerOut.model_validate(CustomerService(db).get(customer_id))


@router.get("/customers/{customer_id}/orders", response_model=list[OrderOut])
def list_customer_orders(
    customer_id: str, db: DbDep, _: Principal = Depends(require(Permission.ORDER_READ))
) -> list[OrderOut]:
    CustomerService(db).get(customer_id)
    return [serialize_order(o) for o in OrderService(db).list_for_customer(customer_id)]


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    db: DbDep, _: Principal = Depends(require(Permission.ORDER_READ))
) -> list[OrderOut]:
    return [serialize_order(o) for o in OrderService(db).list()]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: str, db: DbDep, _: Principal = Depends(require(Permission.ORDER_READ))
) -> OrderOut:
    return serialize_order(OrderService(db).get(order_id))


def _policy_out(policy) -> PolicyOut:
    return PolicyOut(
        id=policy.id,
        name=policy.name,
        version=policy.version,
        is_active=policy.is_active,
        config=PolicyConfig.model_validate(policy.config),
        created_at=policy.created_at,
        created_by=policy.created_by,
    )


@router.get("/policies/active", response_model=PolicyOut)
def active_policy(db: DbDep, _: Principal = Depends(require(Permission.POLICY_READ))) -> PolicyOut:
    return _policy_out(PolicyService(db).get_active())


@router.get("/policies", response_model=list[PolicyOut])
def policy_history(
    db: DbDep, _: Principal = Depends(require(Permission.POLICY_READ))
) -> list[PolicyOut]:
    return [_policy_out(p) for p in PolicyService(db).history()]


@router.put("/policies", response_model=PolicyOut)
def publish_policy(
    config: PolicyConfig,
    db: DbDep,
    principal: Principal = Depends(require(Permission.POLICY_MANAGE)),
) -> PolicyOut:
    policy = PolicyService(db).publish(config, created_by=principal.id)
    db.commit()
    return _policy_out(policy)
