"""S3CheckpointStore against moto's in-process S3, so no credentials or network are needed."""

import hashlib
import os
from pathlib import Path

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
    s3 = store()
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
    assert not [p for p in Path(tempfile_dir()).iterdir() if p.name.startswith(".checkpoint-")], (
        "a failed download leaves no temporary file behind"
    )


def tempfile_dir():
    import tempfile

    return tempfile.gettempdir()


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
