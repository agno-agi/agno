"""Cancel a turn and continue from the last completed one.

A cancelled turn removes its computer and publishes nothing: the session's recovery
point stays the last completed turn. The next turn restores that checkpoint, so
whatever the cancelled turn did to the workspace is gone.

Uses the credential-free fixture runtime. Turn 2 takes six seconds and is cancelled
after three; cancellation goes through agno's run cancellation, the same call
AgentOS uses for its cancel endpoint.

Prerequisites:
    ./cookbook/scripts/run_pgvector.sh
    python cookbook/frameworks/sandbox/build_image.py
"""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.run.cancel import acancel_run
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.coordinator import SandboxCoordinator
from agno.sandbox.docker import DockerCheckpointTransfer, DockerSandbox

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
sandbox = DockerSandbox(
    os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
    namespace="cancel-turn",
    memory_mb=512,
)
session_id = "cancel-" + uuid4().hex[:8]
turn = dict(agent_id="coder", sdk="fixture", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"})


async def main() -> None:
    with TemporaryDirectory() as checkpoints:
        transfer = DockerCheckpointTransfer(
            sandbox, FileCheckpointStore(Path(checkpoints))
        )
        coordinator = SandboxCoordinator(db, sandbox, transfer)

        first = await coordinator.arun(
            session_id, run_id=session_id + "-1", input="Write the first draft", **turn
        )
        print(f"Turn 1: {first.status} - {first.content}")

        second_id = session_id + "-2"
        second = asyncio.create_task(
            coordinator.arun(
                session_id,
                run_id=second_id,
                input="Rewrite everything",
                config={"delay": 6, "steps": 6},
                **turn,
            )
        )
        await asyncio.sleep(3)
        await acancel_run(second_id)
        cancelled = await second
        print(f"Turn 2 cancelled after 3s: {cancelled.status}")

        third = await coordinator.arun(
            session_id,
            run_id=session_id + "-3",
            input="Revise the first draft",
            **turn,
        )
        print(
            f"Turn 3, restored from turn 1's checkpoint: {third.status} - {third.content}"
        )
        await coordinator.aretire_computer(session_id, agent_id=turn["agent_id"])


if __name__ == "__main__":
    asyncio.run(main())
