"""Open a finished run's checkpoint on the host and read the files the turn left behind.

Every completed turn of a sandboxed agent ends in a checkpoint: an archive of the
computer's workspace and the harness's home, stored outside the computer and
published on the run row. The computer may be paused or gone, but the checkpoint
is the exact tree the turn committed. This example opens it through the agent's
public surface and restores it to a host directory, which is how a host process
extracts an engineer's changes as a patch after the container is gone.

agent.checkpoint_store is the store the agent's turns write to: the sandbox's
checkpoints= store, else the host-local default. agent.open_run_checkpoint(run_id)
verifies the archive and yields its path, and CheckpointArchive.restore extracts
it into workspace/ and native/. A run that failed, was cancelled, is still running
or belongs to another agent is refused.

The fixture runtime stands in for Claude or Codex, so no model credentials are
needed; it appends each run id to workspace/fixture-effects.txt.

Prerequisites:
    ./cookbook/scripts/run_pgvector.sh
    python cookbook/frameworks/sandbox/build_image.py
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
session_id = "open-checkpoint-" + uuid4().hex[:8]

# Use storage every replica can reach; a temporary directory is for the example only.
with TemporaryDirectory() as directory:
    root = Path(directory)
    sandbox = DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        namespace="open-checkpoint",
        memory_mb=512,
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
        checkpoints=FileCheckpointStore(root / "checkpoints"),
    )
    agent = FixtureAgent(id="engineer", db=db, sandbox=sandbox)
    print(f"The agent checkpoints to {agent.checkpoint_store.root}")

    print("Turn 1 runs in a new computer and commits a checkpoint.")
    first = agent.run(
        "Write the first draft", session_id=session_id, run_id=session_id + "-1"
    )
    print(f"  run {first.run_id}: {first.status.value}")

    print("Opening turn 1's checkpoint on the host; the store verifies it first.")
    with agent.open_run_checkpoint(first.run_id) as archive:
        print(f"  archive of {archive.stat().st_size} bytes")
        state = CheckpointArchive().restore(archive, root / "turn-1")
    binding = state["binding"]
    print(f"  bound to run {binding['run_id']} of session {binding['session_id']}")
    effects = (
        (root / "turn-1" / "workspace" / "fixture-effects.txt").read_text().split()
    )
    print(f"  workspace/fixture-effects.txt: {effects}")
    native = sorted(path.name for path in (root / "turn-1" / "native").iterdir())
    print(f"  native/ holds the harness home: {native}")

    print("Turn 2 continues the session; its checkpoint holds both turns.")
    second = agent.run(
        "Revise the draft", session_id=session_id, run_id=session_id + "-2"
    )
    with agent.open_run_checkpoint(second.run_id) as archive:
        CheckpointArchive().restore(archive, root / "turn-2")
    effects = (
        (root / "turn-2" / "workspace" / "fixture-effects.txt").read_text().split()
    )
    print(f"  workspace/fixture-effects.txt: {effects}")

    print("Only a completed run of this agent opens:")
    try:
        with agent.open_run_checkpoint(session_id + "-never"):
            pass
    except ValueError as error:
        print(f"  {error}")
    reviewer = FixtureAgent(id="reviewer", db=db, sandbox=sandbox)
    try:
        with reviewer.open_run_checkpoint(second.run_id):
            pass
    except ValueError as error:
        print(f"  {error}")

    print(
        "Done: the computer kept warm for a next turn is removed; the checkpoints stay."
    )
    generation = second.metadata["sandbox"]["generation"]
    handle = sandbox.find(
        session_id, agent_id=agent.get_id(), generation=generation, env=sandbox.env
    )
    if handle is not None:
        sandbox.destroy(handle)
        print(f"  removed generation {generation}")
