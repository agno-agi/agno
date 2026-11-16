"""Shared fixtures for the sandbox integration suites.

The checkpoint store defaults to a directory under the test's tmp_path. With
AGNO_TEST_S3_BUCKET set, every suite runs against S3CheckpointStore instead, on the
endpoint in AGNO_TEST_S3_ENDPOINT (a local MinIO or moto server) with credentials from
the standard AWS environment, so the coordinator and both transfers are exercised with
a store no replica shares a filesystem with. With AGNO_TEST_CHECKPOINT_DB_URL set, they
run against PostgresCheckpointStore on that database, in tables dropped after each test.
"""

import os
from uuid import uuid4

import pytest

S3_BUCKET = os.environ.get("AGNO_TEST_S3_BUCKET")
S3_ENDPOINT = os.environ.get("AGNO_TEST_S3_ENDPOINT")
CHECKPOINT_DB_URL = os.environ.get("AGNO_TEST_CHECKPOINT_DB_URL")


def make_checkpoint_store(tmp_path):
    if CHECKPOINT_DB_URL:
        from agno.db.postgres import PostgresDb
        from agno.sandbox.postgres_checkpoints import PostgresCheckpointStore

        return PostgresCheckpointStore(PostgresDb(db_url=CHECKPOINT_DB_URL), table_name="ckpt_" + uuid4().hex[:12])
    if not S3_BUCKET:
        from agno.sandbox.checkpoint import FileCheckpointStore

        return FileCheckpointStore(tmp_path / "objects")
    from agno.sandbox.s3 import S3CheckpointStore

    return S3CheckpointStore(
        S3_BUCKET,
        prefix="agno-tests/" + uuid4().hex,
        endpoint_url=S3_ENDPOINT,
        region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


@pytest.fixture
def checkpoint_store(tmp_path):
    store = make_checkpoint_store(tmp_path)
    yield store
    if CHECKPOINT_DB_URL:
        store.chunks.drop(store.db.db_engine, checkfirst=True)
        store.objects.drop(store.db.db_engine, checkfirst=True)
        store.db.db_engine.dispose()
