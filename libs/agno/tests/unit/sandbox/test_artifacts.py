import asyncio
import contextlib
import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agno.sandbox.artifacts import SandboxArtifactNotFound, SandboxArtifacts
from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointObjectNotFound, CheckpointRef, FileCheckpointStore


class MemoryCheckpointStore:
    """A checkpoint store whose objects are not local files, for the reads below.

    It stands in for remote storage: every read materializes a temporary copy and
    unlinks it when the caller is done, so anything that held a path past the managed
    access would fail here. Defined beside its consumers rather than imported from the
    storage branch's test module, which these tests must not depend on to run.

    Only the reads these tests drive are implemented; artifact reads go through the
    synchronous access inside a worker thread, so there is no async variant here.
    """

    def __init__(self, directory):
        self.objects = {}
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.materialized = []

    def put(self, source):
        data = Path(source).read_bytes()
        reference = CheckpointRef(hashlib.sha256(data).hexdigest(), len(data))
        self.objects[reference.sha256] = data
        return reference

    def verify(self, reference):
        data = self.objects.get(reference.sha256)
        if data is None:
            raise CheckpointObjectNotFound("Missing checkpoint object")
        if len(data) != reference.size or hashlib.sha256(data).hexdigest() != reference.sha256:
            raise SandboxError("Checkpoint checksum mismatch")

    @contextlib.contextmanager
    def open_archive(self, reference):
        self.verify(reference)
        descriptor, name = tempfile.mkstemp(dir=self.directory)
        path = Path(name)
        self.materialized.append(path)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(self.objects[reference.sha256])
            yield path
        finally:
            path.unlink(missing_ok=True)


@pytest.fixture(params=[True, False], ids=["compressed", "plain"])
def artifact_store(request, tmp_path):
    workspace, native = tmp_path / "workspace", tmp_path / "native"
    workspace.mkdir()
    native.mkdir()
    (workspace / "a.txt").write_bytes(b"a")
    (workspace / "b.txt").write_bytes(b"binary\x00data")
    (workspace / "alias").symlink_to("a.txt")
    (native / "session.db").write_bytes(b"native state")
    identity = {"incarnation": "inc", "agent_id": "agent", "session_id": "session", "run_id": "run"}
    archive = tmp_path / "archive"
    CheckpointArchive(compress=request.param).capture(
        {"workspace": workspace, "native": native}, archive, state={"binding": identity}
    )
    objects = FileCheckpointStore(tmp_path / "objects")
    reference = objects.put(archive)
    record = {
        "checkpoint": {"sha256": reference.sha256, "size": reference.size},
        "checkpoint_identity": identity,
        "incarnation": "inc",
        "last_run_id": "run",
    }
    return SandboxArtifacts(SimpleNamespace(), objects), record


def test_binary_artifact_and_paginated_regular_workspace_listing(artifact_store):
    store, record = artifact_store
    first = store._inspect(record, None, 0, 1)
    second = store._inspect(record, None, 1, 1)
    assert first["total"] == second["total"] == 2
    assert first["files"] == [{"path": "a.txt", "size": 1}]
    assert second["files"] == [{"path": "b.txt", "size": 11}]
    artifact = store._inspect(record, "b.txt", 0, 1)
    assert artifact.content == b"binary\x00data" and artifact.run_id == "run"


@pytest.mark.parametrize("path", ["alias", "native/session.db", "absent"])
def test_symlinks_native_state_and_missing_files_are_not_downloadable(artifact_store, path):
    store, record = artifact_store
    with pytest.raises(SandboxArtifactNotFound):
        store._inspect(record, path, 0, 1)


def test_no_checkpoint_has_no_durable_artifact(artifact_store):
    store, record = artifact_store
    record["checkpoint"] = None
    with pytest.raises(SandboxArtifactNotFound):
        store._inspect(record, "a.txt", 0, 1)


def test_a_staged_candidate_is_not_served_as_the_completed_checkpoint(artifact_store):
    """A capture that has not been committed is not the latest completed checkpoint.

    ``astage_checkpoint`` sets ``staged_checkpoint`` while ``checkpoint`` still holds
    the previous turn's reference; only ``acommit`` promotes it. The staged reference
    here points at no stored object, so consulting it would fail loudly.
    """
    store, record = artifact_store
    record["staged_checkpoint"] = {"sha256": "0" * 64, "size": 1}
    assert store._inspect(record, "a.txt", 0, 1).content == b"a"
    assert store._inspect(record, None, 0, 10)["checkpoint"] == record["checkpoint"]["sha256"]


@pytest.mark.parametrize("compress", [True, False], ids=["compressed", "plain"])
def test_a_store_without_a_local_object_path_can_serve_artifacts(tmp_path, compress):
    """Artifacts must hold only the store contract, not a local object layout.

    The double materializes each read into a temporary file and unlinks it at context
    exit, so anything that kept the path past the managed access would fail here.
    """
    workspace, native = tmp_path / "workspace", tmp_path / "native"
    workspace.mkdir()
    native.mkdir()
    (workspace / "a.txt").write_bytes(b"a")
    (native / "session.db").write_bytes(b"native state")
    identity = {"incarnation": "inc", "agent_id": "agent", "session_id": "session", "run_id": "run"}
    archive = tmp_path / "archive"
    CheckpointArchive(compress=compress).capture(
        {"workspace": workspace, "native": native}, archive, state={"binding": identity}
    )
    objects = MemoryCheckpointStore(tmp_path / "remote")
    assert not hasattr(objects, "root")
    reference = objects.put(archive)
    record = {
        "checkpoint": {"sha256": reference.sha256, "size": reference.size},
        "checkpoint_identity": identity,
        "incarnation": "inc",
        "last_run_id": "run",
    }
    store = SandboxArtifacts(SimpleNamespace(), objects)

    listing = store._inspect(record, None, 0, 10)
    assert listing["files"] == [{"path": "a.txt", "size": 1}]
    assert listing["checkpoint"] == reference.sha256
    artifact = store._inspect(record, "a.txt", 0, 1)
    assert artifact.content == b"a" and artifact.checkpoint == reference.sha256
    with pytest.raises(SandboxArtifactNotFound):
        store._inspect(record, "native/session.db", 0, 1)

    # The stored object is the encoded bytes; the archive it decodes to is not.
    assert reference.size == archive.stat().st_size
    # Every managed path was released, so nothing survives for a later read.
    assert objects.materialized and not any(path.exists() for path in objects.materialized)


def _remote_checkpoint(tmp_path, store_factory):
    workspace, native = tmp_path / "workspace", tmp_path / "native"
    workspace.mkdir()
    native.mkdir()
    (workspace / "a.txt").write_bytes(b"a")
    (workspace / "b.txt").write_bytes(b"binary\x00data")
    (native / "session.db").write_bytes(b"native state")
    identity = {"incarnation": "inc", "agent_id": "agent", "session_id": "session", "run_id": "run"}
    archive = tmp_path / "archive"
    CheckpointArchive().capture({"workspace": workspace, "native": native}, archive, state={"binding": identity})
    objects = store_factory(tmp_path / "remote")
    reference = objects.put(archive)
    return objects, {
        "checkpoint": {"sha256": reference.sha256, "size": reference.size},
        "checkpoint_identity": identity,
        "incarnation": "inc",
        "last_run_id": "run",
    }


def test_a_read_that_fails_inside_the_archive_still_releases_it(tmp_path):
    objects, record = _remote_checkpoint(tmp_path, MemoryCheckpointStore)
    artifacts = SandboxArtifacts(SimpleNamespace(), objects, max_file_bytes=1)
    with pytest.raises(SandboxError, match="download byte limit"):
        artifacts._inspect(record, "b.txt", 0, 1)
    assert objects.materialized and not any(path.exists() for path in objects.materialized)


@pytest.mark.asyncio
async def test_a_cancelled_read_releases_the_archive_before_cancellation_propagates(tmp_path):
    """A cancelled download must not leave the store's materialized copy behind.

    The awaiter is released only after the worker drains, so a caller that retries
    or cleans up on cancellation never races a still-open archive.
    """
    import threading

    from agno.sandbox.checkpoint import _thread

    class GatedStore(MemoryCheckpointStore):
        def __init__(self, directory):
            super().__init__(directory)
            self.entered, self.gate = threading.Event(), threading.Event()

        @contextlib.contextmanager
        def open_archive(self, reference):
            with super().open_archive(reference) as path:
                self.entered.set()
                assert self.gate.wait(10)
                yield path

    objects, record = _remote_checkpoint(tmp_path, GatedStore)
    artifacts = SandboxArtifacts(SimpleNamespace(), objects)
    task = asyncio.create_task(_thread(artifacts._inspect, record, "a.txt", 0, 1))
    assert await asyncio.to_thread(objects.entered.wait, 10)
    task.cancel()
    objects.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert objects.materialized and not any(path.exists() for path in objects.materialized)


def test_an_artifact_read_survives_retention_deleting_the_object_mid_read(artifact_store):
    """Retention runs on its own schedule; a read already under way must not see it.

    The store leases the bytes, so unlinking the canonical name during the read is
    deterministic here rather than a race: the deletion happens the moment the lease
    is handed over, before any archive byte is read.
    """
    artifacts, record = artifact_store
    inner = artifacts.objects

    class DeletesOnLease:
        def __init__(self):
            self.deleted = False

        def __getattr__(self, name):
            return getattr(inner, name)

        @contextlib.contextmanager
        def open_archive(self, ref):
            with inner.open_archive(ref) as path:
                inner.delete(ref)
                self.deleted = True
                yield path

    artifacts.objects = DeletesOnLease()
    artifact = artifacts._inspect(record, "a.txt", 0, 1)
    assert artifact.content == b"a"
    assert artifacts.objects.deleted
    # The object really is gone, so the next request is a storage failure, not a 404.
    artifacts.objects = inner
    with pytest.raises(CheckpointObjectNotFound):
        artifacts._inspect(record, "a.txt", 0, 1)
    with pytest.raises(CheckpointObjectNotFound):
        artifacts._inspect(record, None, 0, 10)
