"""Open a session's checkpoint from S3 many times and download it once.

A host process that reads checkpoints, for example to turn an engineer agent's edits
into a patch after each task, opens the same object again and again. Without a cache
every open downloads the whole archive, up to 1 GiB. With cache_dir set, the store keeps
each downloaded object on local disk under its digest and later opens cost a local hash
instead of a download. The cache is bounded by cache_bytes and evicts the least recently
opened objects, never one a caller still holds open.

Give this process AWS credentials the way any boto3 client takes them, create a bucket,
build the runtime image and run Postgres:

    export AWS_PROFILE=... AWS_DEFAULT_REGION=us-east-1
    aws s3 mb s3://my-agno-checkpoints
    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/docker/checkpoint_cache.py

The fixture runtime stands in for Claude or Codex, so no model credentials are needed.
"""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointRef
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from agno.sandbox.s3 import S3CheckpointStore

# Your bucket. The prefix keeps checkpoints apart from anything else stored in it.
bucket = "my-agno-checkpoints"

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
session_id = "checkpoint-cache-" + uuid4().hex[:8]

with TemporaryDirectory() as directory:
    root = Path(directory)
    store = S3CheckpointStore(
        bucket,
        prefix="sandbox/checkpoints",
        cache_dir=root / "cache",
        cache_bytes=256 * 1024 * 1024,
    )
    # boto3 reports every request it sends; count the object downloads.
    downloads = []
    store.client.meta.events.register(
        "request-created.s3.GetObject", lambda **kwargs: downloads.append(1)
    )

    sandbox = DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        namespace="checkpoint-cache",
        memory_mb=512,
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
        checkpoints=store,
    )
    agent = FixtureAgent(id="engineer", db=db, sandbox=sandbox)

    print("Turn 1 runs in a new computer and checkpoints to the bucket.")
    run = agent.run("Write the first draft", session_id=session_id)
    reference = CheckpointRef(**run.metadata["sandbox"]["checkpoint"])
    print(
        f"  run {run.run_id}: {run.status.value}, checkpoint {reference.sha256[:12]} ({reference.size} bytes)"
    )

    print(
        "Opening that checkpoint five times, as a loop reading edits out of it would:"
    )
    for attempt in range(1, 6):
        started = time.monotonic()
        with store.open_archive(reference) as archive:
            state = CheckpointArchive().restore(archive, root / f"restore-{attempt}")
        elapsed = time.monotonic() - started
        print(
            f"  open {attempt}: {elapsed * 1000:.0f} ms, downloads so far: {len(downloads)}"
        )
    assert len(downloads) == 1, "every open after the first came from the cache"
    assert state["binding"]["run_id"] == run.run_id

    cached = [
        path.name
        for path in (root / "cache").iterdir()
        if not path.name.startswith(".")
    ]
    print(f"Cache directory holds the object under its digest: {cached}")

    print(
        "Another store on this host, pointed at the same cache directory, does not download either:"
    )
    other = S3CheckpointStore(
        bucket, prefix="sandbox/checkpoints", cache_dir=root / "cache"
    )
    other.client.meta.events.register(
        "request-created.s3.GetObject", lambda **kwargs: downloads.append(1)
    )
    with other.open_archive(reference) as archive:
        print(
            f"  opened {archive.stat().st_size} bytes, downloads so far: {len(downloads)}"
        )
    assert len(downloads) == 1

    print(
        "The bucket is still the source of truth: a deleted object is reported missing even though it is cached."
    )
    store.delete(reference)
    try:
        with store.open_archive(reference):
            pass
    except Exception as error:
        print(f"  {type(error).__name__}: {error}")

    generation = run.metadata["sandbox"]["generation"]
    handle = sandbox.find(
        session_id, agent_id=agent.get_id(), generation=generation, env=sandbox.env
    )
    if handle is not None:
        sandbox.destroy(handle)
        print(
            f"Removed the computer kept warm for a next turn, generation {generation}."
        )
