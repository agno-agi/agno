"""Lose the caller mid-turn and pick the turn up from another coordinator.

A turn runs inside its container, not inside the caller. When the caller goes away
(a dropped connection, a restarted server), the coordinator steps back and the
turn keeps running. Any coordinator that later asks for the same run id and input
reattaches to that execution and gets its result; the work is not started again.

Uses the credential-free fixture runtime, which appends the run id to
workspace/fixture-effects.txt once per execution. Its turn here takes ten seconds,
and the caller disconnects after five. Afterwards the example opens the committed
checkpoint and counts the run id: once means the turn's work happened once.

Prerequisites:
    ./cookbook/scripts/run_pgvector.sh
    python cookbook/frameworks/sandbox/build_image.py
"""

import asyncio
import os
import time
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import CheckpointRef, FileCheckpointStore
from agno.sandbox.coordinator import SandboxCoordinator
from agno.sandbox.docker import DockerCheckpointTransfer, DockerSandbox

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
sandbox = DockerSandbox(
    os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
    namespace="resume-after-disconnect",
    memory_mb=512,
)
session_id = "resume-" + uuid4().hex[:8]
turn = dict(
    agent_id="coder",
    sdk="fixture",
    env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
    run_id=session_id + "-1",
    input="Refactor the module",
    config={"delay": 10, "steps": 10},
)


async def main() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        checkpoints = FileCheckpointStore(root / "checkpoints")
        transfer = DockerCheckpointTransfer(sandbox, checkpoints)

        caller = asyncio.create_task(
            SandboxCoordinator(db, sandbox, transfer).arun(session_id, **turn)
        )
        await asyncio.sleep(5)
        caller.cancel()
        with suppress(asyncio.CancelledError):
            await caller
        print("Caller disconnected after 5s; the turn keeps running in its container")

        # Another coordinator, for example on another replica, asks for the same run.
        started = time.monotonic()
        result = await SandboxCoordinator(db, sandbox, transfer).arun(
            session_id, **turn
        )
        print(
            f"Another coordinator picked the turn up: {result.status} - {result.content} "
            f"after {time.monotonic() - started:.1f}s"
        )

        checkpoint = CheckpointRef(
            **db.get_run(result.run_id).metadata["sandbox"]["checkpoint"]
        )
        checkpoints.restore(checkpoint, root / "opened")
        effects = (
            (root / "opened" / "workspace" / "fixture-effects.txt").read_text().split()
        )
        runs = effects.count(result.run_id)
        assert runs == 1, "the turn's work must not run twice"
        print(
            f"The committed workspace records the turn {runs} time: its work ran once, across both coordinators"
        )
        await SandboxCoordinator(db, sandbox, transfer).aretire_computer(
            session_id, agent_id=turn["agent_id"]
        )


if __name__ == "__main__":
    asyncio.run(main())
