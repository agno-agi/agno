"""The cancellation stage rides the fenced run-status patch on Postgres.

``update_run_in_session`` applies ``fields`` onto the stored run JSON, so the
stage needs no adapter knowledge; this pins that the key lands, loads back as
the enum, and that the guard which refuses to overwrite a terminal row still
holds with the extra field present.
"""

import os
import socket
import time
import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.db.postgres import AsyncPostgresDb
from agno.run.agent import RunOutput
from agno.run.base import CancellationStage, RunStatus
from agno.run.status_persist import RunPersistOutcome
from agno.session import AgentSession

PG_URL = os.getenv("AGNO_TEST_PG_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")


def _reachable(url: str) -> bool:
    host_port = url.rsplit("@", 1)[-1].split("/", 1)[0]
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port or 5432)), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(PG_URL), reason=f"Postgres not reachable at {PG_URL}")


@pytest.fixture
def db():
    schema = "cancel_stage_" + uuid.uuid4().hex[:10]
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    database = AsyncPostgresDb(db_url=PG_URL, db_schema=schema)
    try:
        yield database
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


async def _seed_pending_run(db: AsyncPostgresDb, run_id: str, session_id: str = "s1") -> None:
    now = int(time.time())
    session = await db.upsert_session(
        AgentSession(session_id=session_id, agent_id="a1", created_at=now, updated_at=now)
    )
    assert session is not None, "the session row must exist before a run can reference it"
    await db.upsert_run(
        RunOutput(run_id=run_id, session_id=session_id, agent_id="a1", status=RunStatus.pending), session_id=session_id
    )


@pytest.mark.asyncio
async def test_stage_lands_through_the_fenced_patch_and_loads_as_the_enum(db):
    await _seed_pending_run(db, "r-before")
    outcome = await db.update_run_in_session(
        "s1",
        "r-before",
        fields={"status": "CANCELLED", "cancellation_stage": CancellationStage.pending.value},
        content_if_absent="cancelled before execution",
    )
    assert outcome == RunPersistOutcome.UPDATED
    run = await db.get_run("r-before")
    assert isinstance(run, RunOutput)
    assert run.status == RunStatus.cancelled
    assert run.cancellation_stage is CancellationStage.pending
    assert run.content == "cancelled before execution", "the human reason still lands on content"


@pytest.mark.asyncio
async def test_run_without_a_stage_loads_with_none(db):
    """Rows written before the field existed, and cancellations that carry no
    stage, must read back as unknown rather than as any particular value."""
    await _seed_pending_run(db, "r-plain")
    await db.update_run_in_session("s1", "r-plain", fields={"status": "CANCELLED"})
    run = await db.get_run("r-plain")
    assert isinstance(run, RunOutput) and run.status == RunStatus.cancelled
    assert run.cancellation_stage is None
    assert "cancellation_stage" not in run.to_dict()


@pytest.mark.asyncio
async def test_terminal_guard_still_refuses_with_the_extra_field(db):
    """A completed row must not be flipped to CANCELLED by a late cancel
    carrying a stage: the guard keys on status and is indifferent to the
    extra field."""
    await _seed_pending_run(db, "r-done")
    assert await db.update_run_in_session("s1", "r-done", fields={"status": "COMPLETED"}) == RunPersistOutcome.UPDATED
    outcome = await db.update_run_in_session(
        "s1", "r-done", fields={"status": "CANCELLED", "cancellation_stage": CancellationStage.paused.value}
    )
    assert outcome == RunPersistOutcome.TERMINAL_REFUSED
    run = await db.get_run("r-done")
    assert isinstance(run, RunOutput) and run.status == RunStatus.completed
    assert run.cancellation_stage is None


@pytest.mark.asyncio
async def test_transition_helper_persists_the_stage_on_postgres(db):
    """End to end through apersist_run_transition, the helper every
    non-durable cancel path uses: on Postgres the atomic patch wins and the
    whole-run fallback never runs, so the stage must ride the patch. A later
    non-cancelled transition is refused by the terminal-row guard, so the
    stored stage stays with its CANCELLED status."""
    from agno.agent import Agent
    from agno.run.status_persist import apersist_run_transition

    await _seed_pending_run(db, "r-transition")
    agent = Agent(id="a1", db=db)
    run = RunOutput(
        run_id="r-transition",
        session_id="s1",
        agent_id="a1",
        status=RunStatus.cancelled,
        cancellation_stage=CancellationStage.pending,
    )
    await apersist_run_transition(agent, "agent", "s1", run)
    stored = await db.get_run("r-transition")
    assert isinstance(stored, RunOutput) and stored.status == RunStatus.cancelled
    assert stored.cancellation_stage is CancellationStage.pending

    run.status = RunStatus.running
    await apersist_run_transition(agent, "agent", "s1", run)
    assert run.cancellation_stage is None, "the helper clears the object's stale stage"
    refused = await db.update_run_in_session(
        "s1", "r-transition", fields={"status": "RUNNING", "cancellation_stage": None}
    )
    assert refused == RunPersistOutcome.TERMINAL_REFUSED
    stored = await db.get_run("r-transition")
    assert isinstance(stored, RunOutput) and stored.status == RunStatus.cancelled
    assert stored.cancellation_stage is CancellationStage.pending
