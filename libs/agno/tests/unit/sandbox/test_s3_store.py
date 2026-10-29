"""S3CheckpointStore against moto's in-process S3, so no credentials or network are needed."""

import asyncio
import hashlib
import os
import threading
import time

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from agno.sandbox import SandboxError  # noqa: E402
from agno.sandbox.checkpoint import (  # noqa: E402
    CheckpointArchive,
    CheckpointLimits,
    CheckpointObjectNotFound,
    CheckpointRef,
    CheckpointStore,
)
from agno.sandbox.s3 import S3CheckpointStore  # noqa: E402

BUCKET = "agno-checkpoints"
STATE = {"run_id": "r", "native_id": "n", "conversation": ["hello"]}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture
def roots(tmp_path):
    paths = {name: tmp_path / name for name in ("workspace", "native")}
    for path in paths.values():
        path.mkdir()
    (paths["workspace"] / "app.py").write_text("print('hello')")
    (paths["workspace"] / "data.bin").write_bytes(bytes(range(256)) * 64)
    (paths["native"] / "transcript.jsonl").write_text('{"message":"remember this"}\n')
    return paths


def capture(directory, roots, *, limits=CheckpointLimits(), compress=True):
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "checkpoint.tar"
    CheckpointArchive(limits, compress=compress).capture(roots, archive, state=STATE)
    return archive


def store(**kwargs):
    return S3CheckpointStore(BUCKET, prefix="ckpt", region="us-east-1", **kwargs)


def forbidden(**kwargs):
    from botocore.exceptions import ClientError

    raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")


def objects():
    listing = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket=BUCKET)
    return {item["Key"]: item["Size"] for item in listing.get("Contents", [])}


def test_the_store_satisfies_the_contract_and_round_trips_a_checkpoint(tmp_path, roots):
    s3 = store()
    assert isinstance(s3, CheckpointStore)
    reference = s3.put(capture(tmp_path / "src", roots))
    assert objects() == {f"ckpt/{reference.sha256}.tar.gz": reference.size}
    assert s3.verify(reference) is None
    with s3.open_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
        state = CheckpointArchive().restore(path, tmp_path / "restored")
    assert not path.exists(), "the materialized copy is removed when the caller is done"
    assert state == STATE
    assert (tmp_path / "restored" / "workspace" / "app.py").read_text() == "print('hello')"
    assert objects(), "reading never removes the object"


def test_another_host_restores_what_one_host_captured(tmp_path, roots):
    """Two store instances share nothing but the bucket, as two replicas would."""
    reference = store().put(capture(tmp_path / "src", roots))
    other = store()
    state = other.restore(reference, tmp_path / "restored")
    assert state == STATE
    restored = tmp_path / "restored" / "workspace"
    assert (restored / "data.bin").read_bytes() == bytes(range(256)) * 64


def test_put_of_an_existing_object_uploads_nothing(tmp_path, roots, monkeypatch):
    s3 = store()
    reference = s3.put(capture(tmp_path / "src", roots))
    uploads = []
    monkeypatch.setattr(s3.client, "put_object", lambda **kw: uploads.append(kw))
    monkeypatch.setattr(s3.client, "create_multipart_upload", lambda **kw: uploads.append(kw))
    assert s3.put(capture(tmp_path / "again", roots)) == reference
    assert uploads == []


def test_verify_fails_on_a_truncated_or_tampered_object(tmp_path, roots):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    s3 = store(scratch=scratch)
    reference = s3.put(capture(tmp_path / "src", roots))
    client = boto3.client("s3", region_name="us-east-1")
    key = f"ckpt/{reference.sha256}.tar.gz"

    # Truncated: the same metadata, fewer bytes.
    client.put_object(Bucket=BUCKET, Key=key, Body=b"short", Metadata={"sha256": reference.sha256})
    with pytest.raises(SandboxError, match="size"):
        s3.verify(reference)

    # Overwritten by something that does not carry the digest.
    client.put_object(Bucket=BUCKET, Key=key, Body=os.urandom(reference.size))
    with pytest.raises(SandboxError, match="checksum"):
        s3.verify(reference)

    # Tampered with a forged digest and the right size: the metadata check cannot see
    # it, so the bytes are checked when they are read.
    client.put_object(Bucket=BUCKET, Key=key, Body=os.urandom(reference.size), Metadata={"sha256": reference.sha256})
    assert s3.verify(reference) is None
    entered = False
    with pytest.raises(SandboxError, match="checksum"):
        with s3.open_archive(reference):
            entered = True
    assert not entered
    assert list(scratch.iterdir()) == [], "a failed download leaves no temporary file behind"


def test_put_uploads_when_the_existence_check_is_forbidden(tmp_path, roots, monkeypatch):
    """Without s3:ListBucket, S3 answers HEAD on a missing key with 403; put still stores the object."""
    s3 = store()
    real = s3.client.head_object
    calls = []

    def head(**kwargs):
        calls.append(kwargs["Key"])
        if len(calls) == 1:
            return forbidden(**kwargs)
        return real(**kwargs)

    monkeypatch.setattr(s3.client, "head_object", head)
    reference = s3.put(capture(tmp_path / "src", roots))
    assert len(calls) == 2, "the pre-upload HEAD was refused, the post-upload HEAD confirmed the object"
    assert objects() == {f"ckpt/{reference.sha256}.tar.gz": reference.size}

    # verify cannot tell a forbidden key from a missing one, so it reports the refusal.
    monkeypatch.setattr(s3.client, "head_object", forbidden)
    with pytest.raises(Exception, match="403"):
        s3.verify(reference)


def test_a_missing_object_is_a_store_error_through_every_access(tmp_path, roots):
    s3 = store()
    reference = s3.put(capture(tmp_path / "src", roots))
    s3.delete(reference)
    assert objects() == {}
    with pytest.raises(CheckpointObjectNotFound):
        s3.verify(reference)
    with pytest.raises(CheckpointObjectNotFound):
        with s3.open_archive(reference):
            pass
    with pytest.raises(CheckpointObjectNotFound):
        s3.restore(reference, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    # Retention can see an object twice.
    s3.delete(reference)


@pytest.mark.asyncio
async def test_async_access_matches_sync_access(tmp_path, roots):
    s3 = store()
    reference = await s3.aput(capture(tmp_path / "src", roots))
    await s3.averify(reference)
    async with s3.aopen_archive(reference) as path:
        assert path.stat().st_size == reference.size
    assert not path.exists()
    assert (await s3.arestore(reference, tmp_path / "restored")) == STATE
    await s3.adelete(reference)
    with pytest.raises(CheckpointObjectNotFound):
        await s3.averify(reference)


def test_large_objects_upload_in_parts_and_a_crashed_upload_leaves_nothing_readable(tmp_path, roots, monkeypatch):
    (roots["workspace"] / "big.bin").write_bytes(os.urandom(11 * 1024 * 1024))
    source = capture(tmp_path / "src", roots, compress=False)
    s3 = store(part_size=5 * 1024 * 1024)
    reference = CheckpointRef(hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size)
    assert reference.size > 2 * s3.part_size

    parts = []
    real = s3.client.upload_part

    def failing(**kwargs):
        parts.append(kwargs["PartNumber"])
        if kwargs["PartNumber"] == 2:
            raise ConnectionError("network dropped mid-upload")
        return real(**kwargs)

    monkeypatch.setattr(s3.client, "upload_part", failing)
    with pytest.raises(ConnectionError):
        s3.put(source)
    assert parts == [1, 2]
    assert objects() == {}, "an aborted multipart upload is not readable under the key"
    uploads = s3.client.list_multipart_uploads(Bucket=BUCKET).get("Uploads", [])
    assert uploads == [], "and its parts are not left behind"
    with pytest.raises(CheckpointObjectNotFound):
        s3.verify(reference)

    monkeypatch.setattr(s3.client, "upload_part", real)
    assert s3.put(source) == reference
    assert objects() == {f"ckpt/{reference.sha256}.tar.gz": reference.size}
    with s3.open_archive(reference) as path:
        assert path.read_bytes() == source.read_bytes()


def test_the_object_limit_applies_before_any_upload(tmp_path, roots, monkeypatch):
    s3 = store(max_bytes=16)
    uploads = []
    monkeypatch.setattr(s3.client, "put_object", lambda **kw: uploads.append(kw))
    with pytest.raises(SandboxError, match="limit"):
        s3.put(capture(tmp_path / "src", roots))
    assert uploads == []
    with pytest.raises(SandboxError, match="limit"):
        s3.verify(CheckpointRef("0" * 64, 4096))


def test_configuration_is_validated():
    with pytest.raises(ValueError, match="bucket"):
        S3CheckpointStore("")
    with pytest.raises(ValueError, match="part size"):
        S3CheckpointStore(BUCKET, part_size=1024)
    with pytest.raises(ValueError, match="limit"):
        S3CheckpointStore(BUCKET, max_bytes=0)
    assert S3CheckpointStore(BUCKET, prefix="/a/b/").prefix == "a/b/"
    assert S3CheckpointStore(BUCKET, prefix="").key(CheckpointRef("f" * 64, 1)) == "f" * 64 + ".tar.gz"


def test_an_uncached_open_uses_the_scratch_directory_and_yields_a_read_only_copy(tmp_path, roots):
    s3 = store(scratch=tmp_path / "scratch")
    reference = s3.put(capture(tmp_path / "src", roots))
    with s3.open_archive(reference) as path:
        assert path.parent == tmp_path / "scratch"
        assert path.stat().st_mode & 0o777 == 0o400
        with pytest.raises(PermissionError):
            path.write_bytes(b"x")
    assert list((tmp_path / "scratch").iterdir()) == []


def test_a_cached_object_is_downloaded_once(tmp_path, roots, monkeypatch):
    s3 = store(cache_dir=tmp_path / "cache")
    reference = s3.put(capture(tmp_path / "src", roots))
    downloads = []
    real = s3.client.get_object

    def counting(**kwargs):
        downloads.append(kwargs["Key"])
        return real(**kwargs)

    monkeypatch.setattr(s3.client, "get_object", counting)
    for _ in range(3):
        with s3.open_archive(reference) as path:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
            assert path.stat().st_mode & 0o777 == 0o400
    assert len(downloads) == 1, "the second and third opens came from the cache"
    assert (tmp_path / "cache" / reference.sha256).exists()
    # Another store instance on the same host shares the cache.
    other = store(cache_dir=tmp_path / "cache")
    monkeypatch.setattr(other.client, "get_object", lambda **kw: pytest.fail("must not download"))
    assert other.restore(reference, tmp_path / "restored") == STATE


@pytest.mark.asyncio
async def test_the_cache_serves_async_opens_too(tmp_path, roots, monkeypatch):
    s3 = store(cache_dir=tmp_path / "cache")
    reference = await s3.aput(capture(tmp_path / "src", roots))
    async with s3.aopen_archive(reference) as path:
        assert path.stat().st_size == reference.size
    monkeypatch.setattr(s3.client, "get_object", lambda **kw: pytest.fail("must not download"))
    async with s3.aopen_archive(reference) as path:
        assert path.stat().st_size == reference.size
    assert (await s3.arestore(reference, tmp_path / "restored")) == STATE


def test_a_corrupt_cache_entry_is_fetched_again(tmp_path, roots):
    s3 = store(cache_dir=tmp_path / "cache")
    reference = s3.put(capture(tmp_path / "src", roots))
    with s3.open_archive(reference):
        pass
    cached = tmp_path / "cache" / reference.sha256
    cached.chmod(0o600)
    cached.write_bytes(b"corrupt")
    with s3.open_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert hashlib.sha256(cached.read_bytes()).hexdigest() == reference.sha256, "the entry was replaced"


def test_a_cached_copy_does_not_hide_a_deleted_object(tmp_path, roots):
    s3 = store(cache_dir=tmp_path / "cache")
    reference = s3.put(capture(tmp_path / "src", roots))
    with s3.open_archive(reference):
        pass
    s3.delete(reference)
    with pytest.raises(CheckpointObjectNotFound):
        with s3.open_archive(reference):
            pass


def test_eviction_keeps_the_budget_and_never_pulls_an_open_object_away(tmp_path, roots):
    references = []
    for index in range(4):
        (roots["workspace"] / "data.bin").write_bytes(os.urandom(1500))
        references.append(
            S3CheckpointStore(BUCKET, prefix="ckpt", region="us-east-1").put(
                capture(tmp_path / f"src{index}", roots, compress=False)
            )
        )
    # Room for two objects and a bit, so the third open must evict one.
    budget = references[0].size * 2 + 100
    s3 = store(cache_dir=tmp_path / "cache", cache_bytes=budget)

    with s3.open_archive(references[0]) as held:
        for reference in references[1:]:
            with s3.open_archive(reference):
                pass
        cached = {p.name for p in (tmp_path / "cache").iterdir() if not p.name.startswith(".")}
        assert references[-1].sha256 in cached, "the most recent object is kept"
        assert references[0].sha256 not in cached, "the least recently opened was evicted"
        assert sum(p.stat().st_size for p in (tmp_path / "cache").iterdir() if not p.name.startswith(".")) <= budget
        assert hashlib.sha256(held.read_bytes()).hexdigest() == references[0].sha256, "the open lease still reads"
    assert not held.exists()


async def cancel_while_opening(s3, reference):
    async def open_and_hold():
        async with s3.aopen_archive(reference):
            await asyncio.sleep(10)

    task = asyncio.create_task(open_and_hold())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancelling_an_uncached_open_leaves_no_copy_behind(tmp_path, roots):
    s3 = store(scratch=tmp_path / "scratch")
    reference = await s3.aput(capture(tmp_path / "src", roots))
    download = s3._download

    def slow(ref):
        # A thread cannot be interrupted: cancel after its copy exists, before the caller holds it.
        path = download(ref)
        time.sleep(0.5)
        return path

    s3._download = slow
    await cancel_while_opening(s3, reference)
    assert list((tmp_path / "scratch").iterdir()) == []


@pytest.mark.asyncio
async def test_cancelling_a_cached_open_leaves_no_lease_behind(tmp_path, roots):
    s3 = store(cache_dir=tmp_path / "cache")
    reference = await s3.aput(capture(tmp_path / "src", roots))
    enter = s3._open_cached

    def slow(ref):
        # Cancel after the lease exists, before the caller holds it.
        opened = enter(ref)
        time.sleep(0.5)
        return opened

    s3._open_cached = slow
    await cancel_while_opening(s3, reference)
    assert [p.name for p in (tmp_path / "cache").iterdir() if p.name.startswith(".")] == []
    assert (tmp_path / "cache" / reference.sha256).exists(), "the cached object itself stays"


@pytest.mark.asyncio
async def test_a_cached_async_open_verifies_off_the_event_loop(tmp_path, roots, monkeypatch):
    s3 = store(cache_dir=tmp_path / "cache")
    reference = await s3.aput(capture(tmp_path / "src", roots))
    verify = s3.cache._verify
    threads = []

    def recording(path, ref):
        threads.append(threading.current_thread())
        verify(path, ref)

    monkeypatch.setattr(s3.cache, "_verify", recording)
    async with s3.aopen_archive(reference) as path:
        assert path.stat().st_size == reference.size
    assert threads and threading.main_thread() not in threads


def test_a_cached_open_checks_the_digest_once(tmp_path, roots, monkeypatch):
    """The lease's check is the only one: a second full hash per open was pure cost."""
    s3 = store(cache_dir=tmp_path / "cache")
    reference = s3.put(capture(tmp_path / "src", roots))
    with s3.open_archive(reference):  # fill the cache
        pass
    checks = []
    verify = s3.cache._verify
    monkeypatch.setattr(s3.cache, "_verify", lambda path, ref: checks.append(path) or verify(path, ref))
    monkeypatch.setattr(s3.cache, "verify", lambda ref: pytest.fail("the lease already checks the digest"))
    with s3.open_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert len(checks) == 1


@pytest.mark.asyncio
async def test_a_failing_release_keeps_the_cancellation():
    """A cleanup that fails under a cancel is chained on; the caller still sees CancelledError."""
    import asyncio

    from agno.sandbox.checkpoint import _thread

    def work():
        time.sleep(0.3)
        return "resource"

    def release(_):
        raise OSError("cleanup failed")

    task = asyncio.create_task(_thread(work, release=release))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert isinstance(caught.value.__cause__, OSError)
