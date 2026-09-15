"""Persist an Agno step pause; a customer permit gates the local order effect."""

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.workflow import HumanReview, OnReject, Workflow
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from pushary.adapters import AdapterKernel, decision_fingerprint

REVISION = "pushary-agno-order-v1"
ORDER = {"order_id": "order-1", "amount_cents": 1900}


def _question(operation):
    return "Approve order.release? " + json.dumps(operation["order"], sort_keys=True)


def _save(folder, name, value):
    temporary = folder / (name + ".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(folder / name)


def _workflow(folder, operation, grant):
    def release_order(step_input: StepInput) -> StepOutput:
        # A native confirm() call alone must never execute the order effect.
        if not grant["active"] or time.time() >= operation["expires_at"]:
            raise PermissionError("No active customer execution permit")
        grant["active"] = False
        if step_input.input != operation["order"]:
            raise ValueError("Agno step input changed")
        # ponytail: local SQLite demonstrates one host; use your transactional order service in production.
        with sqlite3.connect(folder / "orders.db", timeout=10) as db:
            db.execute("create table if not exists released (id primary key, order_id)")
            db.execute(
                "insert into released values (?,?)",
                (grant["binding"], operation["order"]["order_id"]),
            )
        return StepOutput(
            content={"order_id": operation["order"]["order_id"], "status": "released"}
        )

    return Workflow(
        id=REVISION,
        db=SqliteDb(db_file=str(folder / "workflow.db")),
        telemetry=False,
        steps=[
            Step(
                name="release_order",
                executor=release_order,
                max_retries=0,
                human_review=HumanReview(
                    requires_confirmation=True,
                    confirmation_message=_question(operation),
                    on_reject=OnReject.cancel,
                ),
            )
        ],
    )


def _pause(run, operation):
    if (
        run is None
        or not run.is_paused
        or run.workflow_id != REVISION
        or run.session_id != operation["session_id"]
        or run.user_id != operation["user_id"]
        or run.input != operation["order"]
        or run.pause_kind != "step"
        or run.paused_step_name != "release_order"
        or run.paused_step_index != 0
    ):
        raise ValueError("Unexpected Agno run identity, input or pause")
    requirements = run.steps_requiring_confirmation
    if len(requirements) != 1 or len(run.step_requirements) != 1:
        raise ValueError("Expected exactly one unresolved confirmation")
    requirement = requirements[0]
    if (
        requirement.step_name != "release_order"
        or requirement.confirmed is not None
        or requirement.confirmation_message != _question(operation)
        or requirement.step_input.input != operation["order"]
    ):
        raise ValueError("Native confirmation changed")
    snapshot = run.to_dict()
    snapshot.setdefault(
        "events", []
    )  # Agno restores absent event history as an empty list.
    return requirement, decision_fingerprint(snapshot)


def _run(mode, folder, tenant, customer):
    folder = Path(folder)
    for value in (tenant, customer):
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:@-]{1,100}", value
        ):
            raise ValueError(
                "Use bounded identities from authenticated application state"
            )
    if mode == "start":
        folder.mkdir(mode=0o700)  # A duplicate start must not create another workflow.
        operation = {
            "revision": REVISION,
            "tenant": tenant,
            "customer": customer,
            "order": ORDER.copy(),
            "expires_at": int(time.time()) + 3600,
            "session_id": decision_fingerprint(
                [str(folder.resolve()), tenant, customer]
            ),
            "user_id": decision_fingerprint([tenant, customer]),
        }
        _save(folder, "operation.json", operation)
        workflow = _workflow(folder, operation, {"active": False})
        run = workflow.run(
            operation["order"],
            session_id=operation["session_id"],
            user_id=operation["user_id"],
        )
        _, snapshot_hash = _pause(run, operation)
        _save(
            folder,
            "pending.json",
            {
                "run_id": run.run_id,
                "snapshot_hash": snapshot_hash,
                "operation_hash": decision_fingerprint(operation),
            },
        )
    elif mode != "resume":
        raise ValueError("Use start or resume")

    operation = json.loads((folder / "operation.json").read_text())
    pending = json.loads((folder / "pending.json").read_text())
    if (
        operation["revision"] != REVISION
        or operation["tenant"] != tenant
        or operation["customer"] != customer
        or operation["order"] != ORDER
        or decision_fingerprint(operation) != pending["operation_hash"]
    ):
        raise ValueError("Saved operation differs from the trusted caller")
    if time.time() >= operation["expires_at"]:
        return {"blocked": "Approval expired"}
    grant = {"active": False}
    workflow = _workflow(folder, operation, grant)
    run = workflow.get_run_output(
        pending["run_id"],
        session_id=operation["session_id"],
        user_id=operation["user_id"],
    )
    requirement, snapshot_hash = _pause(run, operation)
    if run.run_id != pending["run_id"] or snapshot_hash != pending["snapshot_hash"]:
        raise ValueError("Saved native run changed")
    binding = decision_fingerprint([operation, pending])

    def execute():
        if time.time() >= operation["expires_at"]:
            raise TimeoutError("Approval expired before native resume")
        grant.update(active=True, binding=binding)
        try:
            requirement.confirm()
            result = workflow.continue_run(run)
            expected = {
                "order_id": operation["order"]["order_id"],
                "status": "released",
            }
            if result.status.value != "COMPLETED" or result.content != expected:
                raise RuntimeError(
                    "Native resume outcome is uncertain; reconcile without retry"
                )
            return result.content
        finally:
            grant["active"] = False

    protect = AdapterKernel("the Agno workflow example").create_protect(
        policy=False, timeout_seconds=0, expires_in_seconds=3600
    )
    result = protect(
        "order.release",
        execute,
        external_id=customer,
        run_id=run.run_id,
        call_id=requirement.step_id,
        target=operation["order"]["order_id"],
        actor=tenant,
        question=_question(operation),
        facts={**operation["order"], "pushary_binding": binding},
    )
    return {"result": result.result} if result.ok else {"blocked": result.reason}


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(
            "Usage: python run.py start|resume STATE_DIRECTORY TENANT TEST_CUSTOMER_ID"
        )
    try:
        print(json.dumps(_run(*sys.argv[1:])))
    except Exception:  # noqa: BLE001 - Never print credentials or HTTP bodies from SDK exceptions.
        raise SystemExit(
            "Stopped safely. Reconcile the saved run and permit before any retry."
        )
