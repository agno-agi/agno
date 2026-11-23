"""A sandboxed agent whose checkpoints live in PostgreSQL instead of a local directory.

A deployment with more than one replica has no shared disk to put checkpoints on, so the
queue worker refuses the local default. A sandboxed agent already needs Postgres, so
PostgresCheckpointStore can keep checkpoints there with no other storage service: each
checkpoint is a row named by the sha256 of its bytes, with those bytes in chunk rows that
every replica can read.

Build the runtime image and run Postgres:

    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/docker/sandbox_postgres_checkpoints.py

The fixture runtime stands in for Claude or Codex, so no model credentials are needed.
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointRef
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from agno.sandbox.postgres_checkpoints import PostgresCheckpointStore
from sqlalchemy import func, select

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
# The agent's own database. Pass a separate PostgresDb to keep checkpoint bytes out of it.
checkpoints = PostgresCheckpointStore(db)

sandbox = DockerSandbox(
    os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
    namespace="postgres-checkpoints",
    memory_mb=512,
    env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
    checkpoints=checkpoints,
)
agent = FixtureAgent(id="engineer", db=db, sandbox=sandbox)
session_id = "postgres-checkpoints-" + uuid4().hex[:8]


def remove_warm_computer(run):
    generation = run.metadata["sandbox"]["generation"]
    handle = sandbox.find(
        session_id, agent_id=agent.get_id(), generation=generation, env=sandbox.env
    )
    if handle is not None:
        sandbox.destroy(handle)
        print(
            f"  removed the computer kept warm for the next turn (generation {generation})"
        )


print("Turn 1 runs in a new computer and checkpoints to Postgres.")
first = agent.run("Write the first draft", session_id=session_id)
reference = CheckpointRef(**first.metadata["sandbox"]["checkpoint"])
with db.db_engine.connect() as connection:
    chunks = connection.execute(
        select(func.count()).where(checkpoints.chunks.c.sha256 == reference.sha256)
    ).scalar()
print(
    f"  checkpoint {reference.sha256[:12]}: {reference.size} bytes in {chunks} rows of "
    f"{checkpoints.chunks.fullname}"
)

# Lose the host: on a real deployment this is a crashed machine or the next turn landing on
# another replica. The only copy of the session's files is now the checkpoint in Postgres.
remove_warm_computer(first)

print("Turn 2 starts a new computer and restores the checkpoint from Postgres into it.")
second = agent.run("Revise the draft", session_id=session_id)
print(f"  resumed a warm computer: {second.metadata['sandbox']['resumed']}")
assert second.metadata["sandbox"]["resumed"] is False

print("Turn 2's checkpoint holds the files both turns wrote:")
with TemporaryDirectory() as directory:
    with agent.open_run_checkpoint(second.run_id) as archive:
        CheckpointArchive().restore(archive, Path(directory) / "restored")
    effects = (
        Path(directory) / "restored" / "workspace" / "fixture-effects.txt"
    ).read_text()
runs = effects.split()
print(f"  fixture-effects.txt lists runs {runs}")
assert runs == [first.run_id, second.run_id]

remove_warm_computer(second)
