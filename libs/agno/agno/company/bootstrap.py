"""Rehydrate code declarations by stable identity without resetting human edits."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import NAMESPACE_URL, uuid5

from agno.company.declarations import Product
from agno.company.execution import _call
from agno.company.routines import _declared_schedule_fields
from agno.db.utils import is_unique_violation
from agno.scheduler import ScheduleManager


async def arehydrate_product(
    db: Any,
    product: Product,
    registry: Any = None,
    schedule_db: Any = None,
    scoped_user_id: Optional[str] = None,
    *,
    agent_os: Any = None,
):
    """Insert declared records once, repair interrupted linking, and retain later edits."""
    import time

    product_id = product.id or str(uuid5(NAMESPACE_URL, "agno:company:product:" + product.name))
    routine_fields = [
        _declared_schedule_fields(product_id, routine, registry, agent_os=agent_os) for routine in product.routines
    ]
    row = await _call(db, "get_product", product_id, include_deleted=True)
    if row is None:
        try:
            row = await _call(
                db,
                "create_product",
                {
                    "id": product_id,
                    "name": product.name,
                    "purpose": product.purpose,
                    "metadata": product.metadata,
                    "user_id": product.user_id,
                    "created_at": int(time.time()),
                    "updated_at": None,
                    "deleted_at": None,
                },
            )
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            row = await _call(db, "get_product", product_id, include_deleted=True)
    if row is None:
        raise RuntimeError("Product rehydration failed")
    from agno.company.playbook import _require_product_scope

    _require_product_scope(row)
    if row.get("deleted_at") is not None:
        return row
    # An existing owner remains authoritative; declarations never reassign ownership.
    for source in product.sources:
        source_id = source.id or str(uuid5(NAMESPACE_URL, product_id + ":" + source.type + ":" + source.reference))
        existing_source = await _call(db, "get_source", source_id, include_deleted=True)
        if existing_source is not None and existing_source["product_id"] != product_id:
            raise ValueError("Source id belongs to another Product")
        if existing_source is None:
            try:
                await _call(
                    db,
                    "create_source",
                    {
                        **source.model_dump(exclude={"id"}),
                        "id": source_id,
                        "product_id": product_id,
                        "user_id": row["user_id"],
                        "created_at": int(time.time()),
                        "updated_at": None,
                        "deleted_at": None,
                    },
                )
            except Exception as exc:
                if not is_unique_violation(exc):
                    raise
                existing_source = await _call(db, "get_source", source_id, include_deleted=True)
                if existing_source is None or existing_source["product_id"] != product_id:
                    raise ValueError("Source id belongs to another Product") from exc
    schedule_db = schedule_db if schedule_db is not None else db
    schedules = ScheduleManager(schedule_db)
    from agno.db.schemas.scheduler import Schedule

    # An existing Routine keeps its owner on a retry; only a new one belongs to its declarer, as on
    # POST /company/routines. Code declarations use the Product owner.
    routine_owner = product.user_id if product.user_id is not None else row["user_id"]
    linked = {}
    for schedule_id in (row.get("metadata") or {}).get("routine_ids") or []:
        found = await _call(schedule_db, "get_schedule", schedule_id)
        if found is not None:
            linked[found["name"]] = found
    for routine, fields in zip(product.routines, routine_fields):
        fields["cron"] = fields.pop("cron_expr")
        existing = linked.get(fields["name"]) or await _call(
            schedule_db, "get_schedule_by_name", fields["name"], user_id=row["user_id"]
        )
        if existing is not None:
            schedule = Schedule.from_dict(existing)
        else:
            try:
                schedule = await schedules.acreate(
                    **fields,
                    user_id=routine_owner,
                    if_exists="skip",
                    provenance={
                        "managed_by": "company",
                        "target_type": routine.executor_type,
                        "target_id": routine.executor_id,
                    },
                )
            except Exception as exc:
                if not is_unique_violation(exc):
                    raise
                existing = await _call(schedule_db, "get_schedule_by_name", fields["name"], user_id=routine_owner)
                if existing is None:
                    raise
                schedule = Schedule.from_dict(existing)
        if (
            schedule.managed_by != "company"
            or (schedule.payload or {}).get("metadata", {}).get("product_id") != product_id
        ):
            raise ValueError("Routine name is already used by another schedule")
        # An archived Routine stays out of the Product's routine_ids until it is restored.
        if (schedule.payload or {}).get("metadata", {}).get("deleted_at") is None:
            row = await _call(db, "add_product_routine", product_id, schedule.id)
    return row


def rehydrate_product(
    db: Any,
    product: Product,
    registry: Any = None,
    schedule_db: Any = None,
    scoped_user_id: Optional[str] = None,
    *,
    agent_os: Any = None,
):
    """Synchronous startup counterpart; use arehydrate_product inside an event loop."""
    return asyncio.run(
        arehydrate_product(
            db, product, registry, schedule_db=schedule_db, scoped_user_id=scoped_user_id, agent_os=agent_os
        )
    )


@asynccontextmanager
async def _company_lifespan(app: Any, agent_os: Any):
    for declaration in agent_os.company.products:
        product = declaration if isinstance(declaration, Product) else Product.model_validate(declaration)
        await arehydrate_product(
            agent_os._company_db, product, agent_os.registry, schedule_db=agent_os.db, agent_os=agent_os
        )
    yield
