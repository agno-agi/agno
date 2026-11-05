"""Run several turns of one session, warm and cold, and see what each turn leaves behind.

The first turn of a session runs on a new container. When a turn completes the
coordinator saves a checkpoint, pauses the container and only then marks the run
completed; the next turn resumes that container with nothing to restore. A
container that is gone or past its warm window is replaced by a new one restored
from the checkpoint, so the checkpoint is always the recovery point. After each
turn this example reads back
what that left, using only public calls: the run row and the session in Postgres,
and the checkpoint itself, opened from the checkpoint store.

The fixture runtime stands in for Claude or Codex, so no model credentials are
needed. It appends each turn's run id to workspace/fixture-effects.txt and keeps a
native conversation id like theirs; every turn after the first must find the id
the previous turn committed.

Prerequisites:
    ./cookbook/scripts/run_pgvector.sh
    python cookbook/frameworks/sandbox/build_image.py
"""

import os
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
    namespace="session-computer",
    memory_mb=512,
)
session_id = "session-computer-" + uuid4().hex[:8]
turn = dict(agent_id="coder", sdk="fixture", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"})


def describe(run_id: str, checkpoints: FileCheckpointStore, scratch: Path) -> None:
    """Print what a finished turn left in Postgres and in the checkpoint store."""
    run = db.get_run(run_id)
    sandbox_metadata = run.metadata["sandbox"]
    print(f"  run {run_id}: {run.status}, content {run.content!r}")
    print(f"  ran on computer generation {sandbox_metadata['generation']}")
    checkpoint = CheckpointRef(**sandbox_metadata["checkpoint"])
    session = db.get_session(session_id)
    assert session.session_data["sandbox"]["checkpoint"]["sha256"] == checkpoint.sha256
    print(
        f"  session now points at checkpoint {checkpoint.sha256[:12]} ({checkpoint.size} bytes)"
    )
    opened = scratch / uuid4().hex
    checkpoints.restore(checkpoint, opened)
    effects = (opened / "workspace" / "fixture-effects.txt").read_text().split()
    print(f"  inside that checkpoint, the workspace has every turn so far: {effects}")


# Use storage every coordinator replica can reach; a temporary directory is for the example only.
with TemporaryDirectory() as directory:
    root = Path(directory)
    checkpoints = FileCheckpointStore(root / "checkpoints")
    coordinator = SandboxCoordinator(
        db, sandbox, DockerCheckpointTransfer(sandbox, checkpoints)
    )

    print("Turn 1: a new session starts on an empty computer.")
    first = coordinator.run(
        session_id, run_id=session_id + "-1", input="Write the first draft", **turn
    )
    describe(first.run_id, checkpoints, root)

    print("Turn 2: turn 1's computer, resumed from its pause; nothing restored.")
    second = coordinator.run(
        session_id, run_id=session_id + "-2", input="Revise the draft", **turn
    )
    describe(second.run_id, checkpoints, root)
    print(
        "  the same generation as turn 1, so no restore happened; its checkpoint was still captured."
    )
    print("  turn 2 completing also means it found turn 1's native conversation.")

    print("Retrying turn 2, say after a lost response:")
    retry = coordinator.run(
        session_id, run_id=second.run_id, input="Revise the draft", **turn
    )
    print(f"  {retry.status}, the stored result; the turn did not run again.")
    describe(second.run_id, checkpoints, root)

    print(
        "Done: the computer kept warm for a next turn is removed; the checkpoint stays."
    )
    removed = coordinator.retire_computer(session_id, agent_id=turn["agent_id"])
    print(f"  removed a warm computer: {removed}")
