"""Persisted run database references resolve across independent processes."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

# Each invocation imports Agno and constructs its own database and AgentOS.
# Store the reference on a Task, as consumers of the run database ID do.
_PROCESS = """
import asyncio
import json
import sys
import time

from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.company import AsyncCompanyManager
from agno.db.postgres import AsyncPostgresDb
from agno.db.sqlite import AsyncSqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.utils import get_db
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

async def main():
    backend, options, mode = sys.argv[1:]
    cls = AsyncPostgresDb if backend == "postgres" else AsyncSqliteDb
    db = cls(**json.loads(options))
    try:
        if mode == "write":
            product = await AsyncCompanyManager(db).create(name="SDK")
            run = RunOutput(
                run_id="prior-run", session_id="task-session", agent_id="writer",
                content="Persisted before restart", status=RunStatus.completed,
            )
            assert await db.upsert_session(AgentSession(
                session_id="task-session", agent_id="writer", created_at=int(time.time()),
            )) is not None
            await db.upsert_run(run, session_id="task-session")
            await db.create_task({
                "id": "task", "product_id": product["id"], "title": "Release",
                "status": "in_progress", "created_at": int(time.time()),
                "session_id": "task-session", "job_id": run.run_id,
                "executor_type": "agent", "executor_id": "writer",
                "transitions": [{"attempt": 1, "run_id": run.run_id, "run_db_id": db.id, "session_id": "task-session"}],
            })
        else:
            task = await db.get_task("task")
            agent_os = AgentOS(
                db=db, agents=[Agent(id="writer", db=db)], company=CompanyConfig(), telemetry=False,
            )
            app = agent_os.get_app()
            resolved = await get_db(agent_os.dbs, db_id=task["transitions"][0]["run_db_id"])
            runs = await resolved.get_runs(session_id=task["transitions"][0]["session_id"])
            assert len(runs) == 1, runs
            assert runs[0].run_id == "prior-run"
            assert runs[0].content == "Persisted before restart"
            assert (await resolved.get_run("prior-run")).content == runs[0].content
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(
                    "/sessions/task-session/runs", params={"db_id": task["transitions"][0]["run_db_id"]},
                )
                assert response.status_code == 200, response.text
                assert response.json()[0]["content"] == "Persisted before restart"
                history = await client.get("/company/tasks/task/runs", params={"limit": 1, "page": 1})
                assert history.status_code == 200, history.text
                assert history.json()["meta"]["total_count"] == 1
                assert history.json()["data"][0]["run_id"] == "prior-run"
                assert history.json()["data"][0]["run_data"]["content"] == "Persisted before restart"
                individual = await client.get("/company/runs/prior-run")
                assert individual.status_code == 200, individual.text
                assert individual.json()["status"] == "COMPLETED"
                assert individual.json()["run_data"]["content"] == "Persisted before restart"
    finally:
        await db.close()

asyncio.run(main())
"""


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_company_run_history_survives_process_restart_and_replica(tmp_path, backend):
    if backend == "postgres":
        try:
            with socket.create_connection(("localhost", 5532), timeout=2):
                pass
        except OSError:
            pytest.skip("Postgres not available on localhost:5532")
    url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
    schema = "company_restart_" + uuid4().hex
    options = (
        {"db_url": url, "db_schema": schema} if backend == "postgres" else {"db_file": str(tmp_path / "history.db")}
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    env.pop("AGNO_DEBUG", None)
    env.pop("AGNO_MONITOR", None)
    try:
        for mode in ("write", "read", "read"):
            result = subprocess.run(
                [sys.executable, "-c", _PROCESS, backend, json.dumps(options), mode],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0, result.stdout + result.stderr
    finally:
        if backend == "postgres":
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    connection.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
            finally:
                engine.dispose()
