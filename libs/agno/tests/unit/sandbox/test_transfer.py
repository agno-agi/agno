import asyncio
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agno.sandbox import SandboxError, SandboxHandle
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointContentError, FileCheckpointStore
from agno.sandbox.docker import DockerCheckpointTransfer, DockerSandbox
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS, CheckpointTransfer


def exported(path, root, entries):
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo(root)
        info.type = tarfile.DIRTYPE
        info.mode = 0o700
        archive.addfile(info)
        for name, kind, value in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.mode = 0o700 if kind == tarfile.DIRTYPE else 0o600
            if kind == tarfile.REGTYPE:
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
            else:
                info.linkname = value
                archive.addfile(info)


def test_combine_converts_hardlinks_and_excludes_native_credentials(tmp_path):
    exported(
        tmp_path / "workspace.tar",
        "workspace",
        [("workspace/file", tarfile.REGTYPE, b"data"), ("workspace/link", tarfile.LNKTYPE, "workspace/file")],
    )
    exported(
        tmp_path / "native.tar",
        "native",
        [
            ("native/codex", tarfile.DIRTYPE, ""),
            ("native/codex/auth.json", tarfile.REGTYPE, b"secret"),
            ("native/codex/thread", tarfile.REGTYPE, b"state"),
        ],
    )
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    transfer._combine(
        {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"},
        tmp_path / "result.tar",
        {"run": "r"},
        DEFAULT_NATIVE_EXCLUSIONS,
    )
    assert CheckpointArchive().validate(tmp_path / "result.tar") == {"run": "r"}
    CheckpointArchive().restore(tmp_path / "result.tar", tmp_path / "restored")
    assert (tmp_path / "restored/workspace/link").read_bytes() == b"data"
    assert not (tmp_path / "restored/native/codex/auth.json").exists()
    (tmp_path / "import").mkdir()
    assert transfer._split(tmp_path / "result.tar", tmp_path / "import") == ({"run": "r"}, 0o700)
    with tarfile.open(tmp_path / "import/workspace.tar") as archive:
        assert archive.getnames() == ["file", "link"]
        assert all(member.uid == member.gid == 1000 for member in archive)


@pytest.mark.parametrize(
    "entries",
    [
        [
            ("native/codex/auth.json", tarfile.REGTYPE, b"secret"),
            ("native/codex/thread", tarfile.LNKTYPE, "native/codex/auth.json"),
        ],
        [
            ("native/codex/thread", tarfile.REGTYPE, b"secret"),
            ("native/codex/auth.json", tarfile.LNKTYPE, "native/codex/thread"),
        ],
    ],
)
def test_combine_rejects_hardlinks_between_excluded_and_retained_paths(tmp_path, entries):
    exported(tmp_path / "workspace.tar", "workspace", [])
    exported(tmp_path / "native.tar", "native", [("native/codex", tarfile.DIRTYPE, ""), *entries])
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    with pytest.raises(SandboxError, match="shares a hardlink"):
        transfer._combine(
            {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"},
            tmp_path / "result.tar",
            {},
            DEFAULT_NATIVE_EXCLUSIONS,
        )


def test_combine_keeps_absolute_virtualenv_links_for_the_next_computer(tmp_path):
    exported(tmp_path / "native.tar", "native", [])
    exported(
        tmp_path / "workspace.tar",
        "workspace",
        [
            ("workspace/.venv", tarfile.DIRTYPE, ""),
            ("workspace/.venv/bin", tarfile.DIRTYPE, ""),
            ("workspace/.venv/bin/python3", tarfile.SYMTYPE, "/usr/local/bin/python3"),
            ("workspace/.venv/bin/python", tarfile.SYMTYPE, "python3"),
            ("workspace/app.py", tarfile.REGTYPE, b"print(1)"),
        ],
    )
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    exports = {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"}
    transfer._combine(exports, tmp_path / "result.tar", {}, DEFAULT_NATIVE_EXCLUSIONS)
    (tmp_path / "import").mkdir()
    transfer._split(tmp_path / "result.tar", tmp_path / "import")
    with tarfile.open(tmp_path / "import/workspace.tar") as archive:
        links = {member.name: member.linkname for member in archive if member.issym()}
    assert links == {".venv/bin/python3": "/usr/local/bin/python3", ".venv/bin/python": "python3"}


def test_combine_rejects_special_files_as_content_it_cannot_checkpoint(tmp_path):
    exported(tmp_path / "native.tar", "native", [])
    exported(tmp_path / "workspace.tar", "workspace", [("workspace/pipe", tarfile.FIFOTYPE, "")])
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    with pytest.raises(CheckpointContentError, match="workspace/pipe"):
        transfer._combine(
            {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"},
            tmp_path / "result.tar",
            {},
            DEFAULT_NATIVE_EXCLUSIONS,
        )


@pytest.mark.parametrize(
    "entries",
    [
        [("workspace/link", tarfile.LNKTYPE, "workspace/missing")],
        [("workspace/link", tarfile.LNKTYPE, "workspace/file"), ("workspace/file", tarfile.REGTYPE, b"data")],
    ],
)
def test_combine_rejects_hardlinks_to_missing_or_later_entries(tmp_path, entries):
    exported(tmp_path / "workspace.tar", "workspace", entries)
    exported(tmp_path / "native.tar", "native", [])
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    with pytest.raises(SandboxError, match="missing or later entry"):
        transfer._combine(
            {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"},
            tmp_path / "result.tar",
            {},
            DEFAULT_NATIVE_EXCLUSIONS,
        )


@pytest.mark.asyncio
async def test_restore_applies_the_captured_native_root_mode(tmp_path):
    exported(tmp_path / "workspace.tar", "workspace", [])
    exported(tmp_path / "native.tar", "native", [])
    provider = DockerSandbox("python:test", namespace="test")
    provider.aexec = AsyncMock(return_value=SimpleNamespace(exit_code=1))
    transfer = DockerCheckpointTransfer(provider, FileCheckpointStore(tmp_path / "objects"))
    transfer._combine(
        {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"}, tmp_path / "result.tar", {}, []
    )
    transfer._check_mounts = AsyncMock()
    reference = transfer.store.put(tmp_path / "result.tar")
    handle = SandboxHandle("id", "name", "a", "s", 1, "running", "digest")
    with pytest.raises(SandboxError, match="empty, unused"):
        await transfer.arestore(handle, reference)
    assert provider.aexec.call_args.args[1][-1].endswith("n.chmod(0o700)")


@pytest.mark.asyncio
async def test_restore_copies_without_archive_mode_and_pins_sandbox_ownership(tmp_path, monkeypatch):
    # Archive mode makes the daemon resolve the "1000:1000" container user as a passwd name and fail.
    exported(tmp_path / "workspace.tar", "workspace", [("workspace/app.py", tarfile.REGTYPE, b"x")])
    exported(tmp_path / "native.tar", "native", [])
    provider = DockerSandbox("python:test", namespace="test")
    provider.aexec = AsyncMock(return_value=SimpleNamespace(exit_code=0))
    transfer = DockerCheckpointTransfer(provider, FileCheckpointStore(tmp_path / "objects"))
    transfer._combine(
        {"workspace": tmp_path / "workspace.tar", "native": tmp_path / "native.tar"}, tmp_path / "result.tar", {}, []
    )
    transfer._check_mounts = transfer._pause = transfer._unpause = AsyncMock()
    reference = transfer.store.put(tmp_path / "result.tar")
    calls = []

    async def spawn(*args, stdin, **kwargs):
        with tarfile.open(fileobj=io.BytesIO(stdin.read())) as archive:
            calls.append((args, [(member.name, member.uid, member.gid) for member in archive]))
        empty = SimpleNamespace(read=AsyncMock(return_value=b""))
        return SimpleNamespace(stdout=empty, stderr=empty, returncode=0, wait=AsyncMock(return_value=0))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    handle = SandboxHandle("id", "name", "a", "s", 1, "running", "digest")
    await transfer.arestore(handle, reference)
    assert [args[1:] for args, _ in calls] == [
        ("container", "cp", "-", "id:/workspace"),
        ("container", "cp", "-", "id:/runtime/native"),
    ]
    assert calls[0][1] == [("app.py", 1000, 1000)]


def test_capture_combine_rejects_wrong_export_root(tmp_path):
    exported(tmp_path / "workspace.tar", "other", [])
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    with pytest.raises(SandboxError):
        transfer._combine({"workspace": tmp_path / "workspace.tar"}, tmp_path / "result.tar", {}, [])


def test_validate_checks_composed_links_without_creating_files(tmp_path, monkeypatch):
    source = tmp_path / "checkpoint.tar"
    with tarfile.open(source, "w") as archive:
        payload = b'{"version":1,"state":{}}'
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        for root in ("workspace", "native"):
            info = tarfile.TarInfo(root)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        for name, target in (("workspace/a", "."), ("workspace/b", "a/../native")):
            info = tarfile.TarInfo(name)
            info.type, info.linkname = tarfile.SYMTYPE, target
            archive.addfile(info)
    monkeypatch.setattr(Path, "mkdir", lambda *a, **kw: pytest.fail("Validation must not extract files"))
    with pytest.raises(SandboxError, match="chain escapes"):
        CheckpointArchive().validate(source)


@pytest.mark.asyncio
async def test_namespace_tmpfs_is_rejected_before_capture(tmp_path):
    provider = DockerSandbox("python:test", namespace="test")
    handle = SandboxHandle("id", "name", "a", "s", 1, "running", "digest")
    provider._owned = AsyncMock(return_value=handle)
    provider._docker = AsyncMock(return_value=(0, json.dumps([{"Mounts": []}]).encode(), b""))
    transfer = DockerCheckpointTransfer(provider, FileCheckpointStore(tmp_path / "objects"))
    with pytest.raises(SandboxError, match="checkpointable"):
        await transfer.acapture(handle, state={})
    assert provider._docker.call_count == 1


@pytest.mark.asyncio
async def test_lost_pause_response_resumes_before_reporting_failure(tmp_path):
    provider = DockerSandbox("python:test", namespace="test")
    running = SandboxHandle("id", "name", "a", "s", 1, "running", "digest")
    paused = SandboxHandle("id", "name", "a", "s", 1, "paused", "digest")
    provider._owned = AsyncMock(side_effect=[running, paused, running])
    provider._docker = AsyncMock(side_effect=[TimeoutError("lost pause"), (0, b"", b"")])
    transfer = DockerCheckpointTransfer(provider, FileCheckpointStore(tmp_path / "objects"))
    with pytest.raises(TimeoutError, match="lost pause"):
        await transfer._pause(running)
    assert provider._docker.call_args.args == ("container", "unpause", "id")


def _paused_capture(tmp_path, unpause):
    transfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    transfer._check_mounts = AsyncMock()
    transfer.provider.aexec = AsyncMock(return_value=SimpleNamespace(exit_code=0))
    transfer._pause = AsyncMock()
    copying = asyncio.Event()

    async def copy(*args, **kwargs):
        copying.set()
        await asyncio.Event().wait()

    transfer._copy = copy
    transfer._unpause = unpause
    handle = SandboxHandle("id", "name", "a", "s", 1, "running", "digest")
    return asyncio.create_task(transfer.acapture(handle, state={})), copying


@pytest.mark.asyncio
async def test_capture_waits_for_unpause_under_repeated_cancellation(tmp_path):
    unpausing, release, finished = asyncio.Event(), asyncio.Event(), []

    async def unpause(handle):
        unpausing.set()
        await release.wait()
        finished.append(True)

    task, copying = _paused_capture(tmp_path, unpause)
    await copying.wait()
    task.cancel()
    await unpausing.wait()
    for _ in range(2):
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished == [True]


@pytest.mark.asyncio
async def test_capture_cancellation_survives_a_failed_unpause(tmp_path):
    async def unpause(handle):
        await asyncio.sleep(0)
        raise SandboxError("unpause failed")

    task, copying = _paused_capture(tmp_path, unpause)
    await copying.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_docker_transfer_satisfies_the_transfer_protocol(tmp_path):
    transfer: CheckpointTransfer = DockerCheckpointTransfer(
        DockerSandbox("python:test", namespace="test"), FileCheckpointStore(tmp_path / "objects")
    )
    assert isinstance(transfer, CheckpointTransfer)
    assert not isinstance(object(), CheckpointTransfer)
