"""Maintain a Company playbook and decision log without a model.

Prerequisites: Install agno, sqlalchemy and aiosqlite.
Run: .venv/bin/python cookbook/05_agent_os/30_company/04_manage_playbook.py
Try: Write with an old version; the edit must be refused.
"""

import asyncio
from tempfile import TemporaryDirectory

from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.fs.errors import VersionConflictError


async def async_example(path: str) -> None:
    db = AsyncSqliteDb(db_file=path)
    manager = AsyncCompanyManager(db)
    product = await manager.create(
        name="Documentation", purpose="Help developers", user_id="alice"
    )
    page = await manager.read_wiki(product["id"], "status.md")
    await manager.write_wiki(
        product_id=product["id"],
        path="status.md",
        content="# Status\n\nDraft ready for review.\n",
        expected_version=page.metadata.version,
        user_id="alice",
    )
    await manager.log_decision(
        decision="Review the draft", reasoning="Examples changed", user_id="alice"
    )
    assert (await manager.list_decisions())[1] == 1
    await db.close()


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        manager = CompanyManager(db)
        product = manager.create(
            name="SDK", purpose="Build reliable agents", user_id="alice"
        )
        page = manager.read_wiki(product["id"], "status.md")
        manager.write_wiki(
            product_id=product["id"],
            path="status.md",
            content="# Status\n\nRelease proposed.\n",
            expected_version=page.metadata.version,
            user_id="alice",
        )
        try:
            manager.write_wiki(
                product_id=product["id"],
                path="status.md",
                content="Stale overwrite",
                expected_version=page.metadata.version,
                user_id="alice",
            )
        except VersionConflictError:
            print("Stale wiki edit refused")
        else:
            raise AssertionError("A stale edit overwrote the page")
        manager.log_decision(
            decision="Review before release",
            reasoning="Human approval is required",
            user_id="alice",
        )
        assert manager.list_decisions()[1] == 1
        assert manager.list_wiki()[1] == 2
        db.close()
        asyncio.run(async_example(directory + "/async-company.db"))
        print("Company playbook sync and async examples passed")
