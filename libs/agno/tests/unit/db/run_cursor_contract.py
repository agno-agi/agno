"""Shared contract for the get_runs cursor filters, has_unindexed_runs and get_session(include_runs).

Each adapter test seeds the same session through the public run API and runs these checks, sync or async.
"""

import inspect
from typing import Any, Dict, List, Optional

from agno.session import AgentSession

SESSION_ID = "cursor-session"

# (run_id, run_index, parent_run_id, status); created_at is 1000 + run_index.
SEEDED_RUNS = [
    ("r0", 0, None, "COMPLETED"),
    ("r1", 1, None, "COMPLETED"),
    ("c1", 2, "r1", "COMPLETED"),
    ("g1", 3, "c1", "COMPLETED"),
    ("r2", 4, None, "ERROR"),
    ("orphan", 5, "gone", "COMPLETED"),
    ("r3", 6, None, "COMPLETED"),
]


async def _call(db: Any, method: str, **kwargs: Any) -> Any:
    result = getattr(db, method)(**kwargs)
    return await result if inspect.isawaitable(result) else result


def _run(run_id: str, run_index: int, parent_run_id: Optional[str], status: str) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "agent_id": "agent-1",
        "session_id": SESSION_ID,
        "parent_run_id": parent_run_id,
        "status": status,
        "created_at": 1000 + run_index,
    }


async def seed(db: Any) -> None:
    session = AgentSession(session_id=SESSION_ID, agent_id="agent-1", user_id="u1", created_at=1000, updated_at=1000)
    await _call(db, "upsert_session", session=session)
    for run_id, run_index, parent_run_id, status in SEEDED_RUNS:
        await _call(
            db,
            "upsert_run",
            run=_run(run_id, run_index, parent_run_id, status),
            session_id=SESSION_ID,
            user_id="u1",
            run_index=run_index,
        )


async def _ids(db: Any, **kwargs: Any) -> List[str]:
    rows, _ = await _call(db, "get_runs", session_id=SESSION_ID, deserialize=False, **kwargs)
    return [row["run_id"] for row in rows]


async def check_contract(db: Any) -> None:
    await seed(db)

    assert await _call(db, "has_unindexed_runs", session_id=SESSION_ID) is False

    rows, count = await _call(db, "get_runs", session_id=SESSION_ID, deserialize=False, top_level_only=True)
    assert [row["run_id"] for row in rows] == ["r0", "r1", "r2", "orphan", "r3"]
    assert count == 5
    assert all(isinstance(row["run_data"], dict) and row["run_data"]["run_id"] == row["run_id"] for row in rows)
    assert [row["run_index"] for row in rows] == [0, 1, 4, 5, 6]

    rows, count = await _call(
        db,
        "get_runs",
        session_id=SESSION_ID,
        deserialize=False,
        top_level_only=True,
        before_run_index=6,
        limit=2,
        sort_by="run_index",
        sort_order="desc",
    )
    assert [(row["run_id"], row["run_index"]) for row in rows] == [("orphan", 5), ("r2", 4)]
    assert count == 4

    rows, count = await _call(
        db, "get_runs", session_id=SESSION_ID, deserialize=False, top_level_only=True, after_run_index=0, limit=2
    )
    assert [row["run_id"] for row in rows] == ["r1", "r2"]
    assert count == 4

    assert await _ids(db, top_level_only=True, status=["ERROR"]) == ["r2"]
    assert await _ids(db, top_level_only=True, status=["ERROR", "COMPLETED"]) == ["r0", "r1", "r2", "orphan", "r3"]
    assert await _ids(db, status="ERROR") == ["r2"]
    assert sorted(await _ids(db, parent_run_ids=["r1", "c1"])) == ["c1", "g1"]
    assert await _ids(db, parent_run_ids=[]) == []
    assert sorted(await _ids(db, created_after=1002, created_before=1005)) == ["c1", "g1", "orphan", "r2"]

    assert len(await _call(db, "get_runs", session_id=SESSION_ID)) == len(SEEDED_RUNS)

    session = await _call(db, "get_session", session_id=SESSION_ID, deserialize=False, include_runs=False)
    assert session["session_id"] == SESSION_ID
    assert session.get("runs") is None

    session = await _call(db, "get_session", session_id=SESSION_ID, deserialize=False)
    assert [(run["run_id"], run.get("run_index")) for run in session["runs"]] == [
        (run_id, run_index) for run_id, run_index, _, _ in SEEDED_RUNS
    ]

    await _call(db, "delete_run", run_id="r1")
    session = await _call(db, "get_session", session_id=SESSION_ID, deserialize=False)
    assert [run.get("run_index") for run in session["runs"]] == [0, 2, 3, 4, 5, 6]
    assert await _ids(db, top_level_only=True) == ["r0", "c1", "r2", "orphan", "r3"]
    assert await _call(db, "has_unindexed_runs", session_id=SESSION_ID) is False
