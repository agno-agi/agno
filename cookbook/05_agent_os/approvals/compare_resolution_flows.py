"""
Compare Resolution Flows
========================

Side-by-side demonstration of how the two AgentOS approval UIs resolve a
paused run with multiple requirements:

  - os.agno.com web UI: one Approve/Reject per whole approval
    (POST /approvals/{id}/resolve flips the aggregate status in one call).
  - Slack HITL (PR #7574): one Approve/Reject per RunRequirement row
    (each click writes a per-row entry inside approval.resolution_data).

No network, no agent run, no OpenAI call — a synthetic paused approval is
inserted into SQLite and both code paths exercise the same DB function.
The third scenario shows the concurrency gap between the two models.
"""

import asyncio
import os
import time
import uuid
from pathlib import Path

from agno.db.sqlite import SqliteDb

DB_FILE = "tmp/compare_resolution.db"


def _build_approval() -> dict:
    now = int(time.time())
    return {
        "id": f"appr_{uuid.uuid4().hex[:8]}",
        "run_id": "run_demo",
        "session_id": "sess_demo",
        "source_type": "agent",
        "agent_id": "demo_agent",
        "source_name": "Demo Agent",
        "status": "pending",
        "approval_type": "required",
        "pause_type": "confirmation",
        "requirements": [
            {
                "id": "req_delete",
                "tool_execution": {
                    "tool_name": "delete_file",
                    "tool_args": {"path": "/tmp/demo.txt"},
                },
            },
            {
                "id": "req_transfer",
                "tool_execution": {
                    "tool_name": "transfer_funds",
                    "tool_args": {"account_id": "42", "amount_usd": 500},
                },
            },
        ],
        "resolution_data": None,
        "context": {"tool_names": ["delete_file", "transfer_funds"]},
        "resolved_by": None,
        "resolved_at": None,
        "run_status": "paused",
        "created_at": now,
        "updated_at": now,
    }


def _reset(db: SqliteDb) -> dict:
    approval = _build_approval()
    if db.get_approval(approval["id"]):
        db.delete_approval(approval["id"])
    db.create_approval(approval)
    return approval


def _dump(label: str, approval: dict) -> None:
    status = approval.get("status") if approval else "<missing>"
    rd = (approval or {}).get("resolution_data") or {}
    rows = rd.get("requirement_resolutions") or {}
    print(f"  {label}")
    print(f"    aggregate status : {status!r}")
    if rows:
        for req_id, row in rows.items():
            print(f"    row {req_id:13s}: {row}")
    else:
        print("    per-row data     : (none)")


def scenario_web_ui(db: SqliteDb) -> None:
    print("\n" + "=" * 72)
    print("Scenario A  —  os.agno.com web UI (single Approve/Reject)")
    print("=" * 72)
    approval = _reset(db)
    _dump("before", db.get_approval(approval["id"]))

    # Mirrors POST /approvals/{id}/resolve in agno/os/routers/approvals/router.py
    after = db.update_approval(
        approval["id"],
        expected_status="pending",
        status="approved",
        resolved_by="admin@example.com",
        resolved_at=int(time.time()),
    )
    _dump("after 1 call", after)


def scenario_slack_sequential(db: SqliteDb) -> None:
    print("\n" + "=" * 72)
    print("Scenario B  —  Slack HITL (per-row, sequential clicks)")
    print("=" * 72)
    approval = _reset(db)
    _dump("before", db.get_approval(approval["id"]))

    # Alice clicks Approve on row 1
    current = db.get_approval(approval["id"])
    rd = dict(current.get("resolution_data") or {})
    rd["requirement_resolutions"] = {
        "req_delete": {"status": "approved", "actor": "U_ALICE"}
    }
    db.update_approval(approval["id"], expected_status="pending", resolution_data=rd)
    _dump("after Alice approves row 1", db.get_approval(approval["id"]))

    # Bob clicks Approve on row 2 (reads Alice's state first)
    current = db.get_approval(approval["id"])
    rd = dict(current.get("resolution_data") or {})
    existing_rows = dict(rd.get("requirement_resolutions") or {})
    existing_rows["req_transfer"] = {"status": "approved", "actor": "U_BOB"}
    rd["requirement_resolutions"] = existing_rows
    db.update_approval(approval["id"], expected_status="pending", resolution_data=rd)
    _dump("after Bob approves row 2", db.get_approval(approval["id"]))

    # Last-row resolver flips aggregate status (interactions.py does this
    # after acontinue_run succeeds).
    db.update_approval(
        approval["id"],
        expected_status="pending",
        status="approved",
        resolved_by="U_BOB",
        resolved_at=int(time.time()),
    )
    _dump("after aggregate flip", db.get_approval(approval["id"]))


async def _click(db: SqliteDb, approval_id: str, row_id: str, actor: str) -> None:
    # Each "click" reads approval, merges its own row into resolution_data,
    # writes back. The 10ms sleep holds both coroutines at the same snapshot
    # so their writes interleave — this is the window Slack cannot serialize.
    current = db.get_approval(approval_id)
    rd = dict(current.get("resolution_data") or {})
    existing_rows = dict(rd.get("requirement_resolutions") or {})
    await asyncio.sleep(0.01)
    existing_rows[row_id] = {"status": "approved", "actor": actor}
    rd["requirement_resolutions"] = existing_rows
    db.update_approval(approval_id, expected_status="pending", resolution_data=rd)


async def scenario_slack_race(db: SqliteDb) -> None:
    print("\n" + "=" * 72)
    print("Scenario C  —  Slack HITL (concurrent clicks on DIFFERENT rows)")
    print("=" * 72)
    approval = _reset(db)
    _dump("before", db.get_approval(approval["id"]))

    await asyncio.gather(
        _click(db, approval["id"], "req_delete", "U_ALICE"),
        _click(db, approval["id"], "req_transfer", "U_BOB"),
    )
    _dump("after two concurrent writes", db.get_approval(approval["id"]))
    final = db.get_approval(approval["id"])
    rows = (final.get("resolution_data") or {}).get("requirement_resolutions") or {}
    if len(rows) < 2:
        print("  !! vote lost: one row is missing from resolution_data")
    else:
        print("  (both rows present — rerun to catch the narrow window)")


def main() -> None:
    Path("tmp").mkdir(parents=True, exist_ok=True)
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    db = SqliteDb(db_file=DB_FILE, approvals_table="approvals")

    scenario_web_ui(db)
    scenario_slack_sequential(db)
    asyncio.run(scenario_slack_race(db))

    print("\n" + "=" * 72)
    print("Takeaway")
    print("=" * 72)
    print("  Web UI (A): lock field == write field (both are status).        Safe.")
    print("  Slack  (B): sequential per-row writes preserve state.           Safe.")
    print("  Slack  (C): concurrent per-row writes both pass the aggregate")
    print("              CAS; the later write clobbers the earlier row.     Broken.")
    print()
    print(
        "  To bring multi-row resolution to os.agno.com, POST /approvals/{id}/resolve"
    )
    print("  would need a per-requirement payload AND either (a) a JSON-path CAS")
    print("  predicate on the row's status, or (b) an asyncio.Lock keyed by")
    print("  approval_id wrapping the read-modify-write.")


if __name__ == "__main__":
    main()
