"""Archive and restore Company hierarchies without a model.

Prerequisites: Install agno, sqlalchemy and aiosqlite. For --postgres, run
cookbook/scripts/run_pgvector.sh and install psycopg.
Run: .venv/bin/python cookbook/05_agent_os/30_company/07_cascading_archive.py
Try: Add --postgres to exercise PostgreSQL, or change the active Task's status.
"""

import argparse
import asyncio
import inspect
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.agent import Agent
from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.registry import Registry
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Archive, restore, and move work with both manager variants
# ---------------------------------------------------------------------------
async def exercise(db):
    registry = Registry(agents=[Agent(id="writer", telemetry=False)])
    manager = (
        AsyncCompanyManager(db, registry=registry)
        if isinstance(db, AsyncBaseDb)
        else CompanyManager(db, registry=registry)
    )

    async def call(method, *args, **kwargs):
        result = method(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    product = await call(manager.create, name="Documentation")
    first = await call(
        manager.create_project, product_id=product["id"], name="Release guide"
    )
    second = await call(
        manager.create_project, product_id=product["id"], name="Next release"
    )
    old = await call(
        manager.create_task,
        product_id=product["id"],
        title="Superseded draft",
        project_id=first["id"],
    )
    await call(manager.delete_task, old["id"])
    task = await call(
        manager.create_task,
        product_id=product["id"],
        title="Write guide",
        project_id=first["id"],
    )
    await call(manager.update_task, task["id"], project_id=second["id"])
    await call(manager.delete_project, first["id"])
    assert await call(manager.get_task, task["id"])
    await call(
        manager.transition_task,
        task_id=task["id"],
        target="ready",
        reason="Scope agreed",
        executor_type="agent",
        executor_id="writer",
    )
    accepted = await call(manager.get_task, task["id"])
    await call(manager.delete_task, task["id"])
    restored = await call(manager.restore_task, task["id"])
    assert restored["transitions"] == accepted["transitions"]
    print("Task archive and restore preserved acceptance history")
    try:
        await call(manager.delete, product["id"])
    except ValueError as exc:
        assert exc.args[0]["tasks"] == [{"id": task["id"], "title": "Write guide"}]
        print("Archive refused with the active Task id and title")
    else:
        raise AssertionError("Active work was archived")
    await call(
        manager.transition_task,
        task_id=task["id"],
        target="cancelled",
        reason="Defer this release",
    )
    assert (await call(manager.get, product["id"]))["counts"]["tasks"]["cancelled"] == 1
    await call(manager.delete, product["id"])
    assert (await call(manager.get, product["id"], include_deleted=True))["counts"][
        "projects"
    ] == 0
    assert await call(manager.list_tasks, include_deleted=True) == ([], 0)
    assert await call(manager.list_projects, include_deleted=True) == ([], 0)
    saved = await call(manager.get_task, task["id"], include_deleted=True)
    assert saved["transitions"][-1]["archived_by"]["id"] == product["id"]
    await call(manager.restore, product["id"])
    assert await call(manager.get_task, task["id"])
    assert await call(manager.get_project, first["id"]) is None
    assert await call(manager.get_task, old["id"]) is None
    await call(manager.restore_project, first["id"])
    assert await call(manager.get_task, old["id"]) is None
    print("Exact cascading restore passed")


async def main(postgres):
    with TemporaryDirectory() as directory:
        for asynchronous in [False, True]:
            if postgres:
                cls = AsyncPostgresDb if asynchronous else PostgresDb
                db = cls(
                    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
                    db_schema="archive_demo_" + uuid4().hex[:12],
                )
            else:
                cls = AsyncSqliteDb if asynchronous else SqliteDb
                db = cls(
                    db_file=directory + ("/async.db" if asynchronous else "/sync.db")
                )
            try:
                await exercise(db)
            finally:
                if postgres:
                    # Remove only this run's disposable schema.
                    statement = text('DROP SCHEMA "' + db.db_schema + '" CASCADE')
                    if asynchronous:
                        async with db.db_engine.begin() as conn:
                            await conn.execute(statement)
                    else:
                        with db.db_engine.begin() as conn:
                            conn.execute(statement)
                result = db.close()
                if inspect.isawaitable(result):
                    await result
    print("Company cascading archive passed for sync and async")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise Company cascading archive")
    parser.add_argument("--postgres", action="store_true")
    asyncio.run(main(parser.parse_args().postgres))
