import asyncio
import contextlib
import errno
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import traceback
from pathlib import Path

import pytest

from agno.sandbox import SandboxError
from agno.sandbox import checkpoint as checkpoint_module
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointContentError,
    CheckpointLimits,
    CheckpointObjectNotFound,
    CheckpointRef,
    CheckpointStore,
    FileCheckpointStore,
)


@pytest.fixture
def roots(tmp_path):
    paths = {name: tmp_path / name for name in ("workspace", "native")}
    for path in paths.values():
        path.mkdir()
    (paths["workspace"] / "tracked.py").write_text("print('hello')")
    (paths["workspace"] / ".gitignore").write_text("ignored\n")
    (paths["workspace"] / "ignored").write_bytes(b"ignored data")
    (paths["workspace"] / "untracked").write_bytes(bytes(range(256)))
    (paths["native"] / "transcript.jsonl").write_text('{"message":"remember this"}\n')
    (paths["native"] / "auth.json").write_text("credential")
    (paths["workspace"] / "link").symlink_to("tracked.py")
    (paths["workspace"] / "tracked.py").chmod(0o751)
    return paths


def capture(tmp_path, roots, *, compress=True, limits=CheckpointLimits()):
    # Created here so a test can capture the same roots twice into separate directories;
    # capture refuses to overwrite a destination.
    tmp_path.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "checkpoint.tar"
    CheckpointArchive(limits, compress=compress).capture(
        roots, archive, state={"run_id": "r", "native_id": "n", "conversation": ["hello"]}, exclude=["native/auth.json"]
    )
    return archive


def test_capture_store_restore_preserves_all_declared_files(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)
    assert reference == store.put(source)
    destination = tmp_path / "restored"
    state = store.restore(reference, destination)
    assert state == {"run_id": "r", "native_id": "n", "conversation": ["hello"]}
    assert (destination / "workspace/untracked").read_bytes() == bytes(range(256))
    assert (destination / "workspace/ignored").read_text() == "ignored data"
    assert (destination / "workspace/link").is_symlink()
    assert (destination / "workspace/link").read_text() == "print('hello')"
    assert (destination / "workspace/tracked.py").stat().st_mode & 0o777 == 0o751
    assert not (destination / "native/auth.json").exists()
    assert len(list(store.root.iterdir())) == 1


def test_hardlinked_source_files_are_copied_as_regular_bytes(tmp_path, roots):
    os.link(roots["workspace"] / "tracked.py", roots["workspace"] / "hardlink")
    source = capture(tmp_path, roots)
    CheckpointArchive().restore(source, tmp_path / "restored")
    assert (tmp_path / "restored/workspace/hardlink").read_text() == "print('hello')"


@pytest.mark.parametrize("compress", [True, False])
@pytest.mark.asyncio
async def test_missing_nofollow_fails_clearly_and_cleans_up(tmp_path, roots, monkeypatch, compress):
    source = capture(tmp_path / "source", roots, compress=compress)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)
    archive = CheckpointArchive(compress=compress)
    monkeypatch.delattr(os, "O_NOFOLLOW")
    for _ in range(2):
        with pytest.raises(SandboxError, match="requires.*O_NOFOLLOW"):
            await archive.acapture(roots, tmp_path / "rejected.tar", state={})
        with pytest.raises(SandboxError, match="requires.*O_NOFOLLOW"):
            await store.aput(source)
        with pytest.raises(SandboxError, match="requires.*O_NOFOLLOW"):
            store.verify(reference)
        with pytest.raises(SandboxError, match="requires.*O_NOFOLLOW"):
            await archive.arestore(source, tmp_path / "restored")
        with pytest.raises(SandboxError, match="requires.*O_NOFOLLOW"):
            async with store.aopen_archive(reference):
                pytest.fail("unsupported archive access must not yield")
        assert not (tmp_path / "rejected.tar").exists()
        assert not (tmp_path / "restored").exists()
        assert not list(tmp_path.glob(".restore-*"))
        assert list(store.root.iterdir()) == [store.root / reference.sha256]


@pytest.mark.parametrize(
    "failure",
    [
        NotImplementedError(),
        OSError(errno.ENOSYS, "unavailable"),
        OSError(errno.ENOTSUP, "unsupported"),
        OSError(errno.EOPNOTSUPP, "unsupported"),
        PermissionError(errno.EACCES, "denied"),
        OSError(errno.ENOSPC, "full"),
        OSError(errno.EIO, "I/O failure"),
    ],
)
@pytest.mark.asyncio
async def test_hardlink_capability_errors_preserve_other_failures(tmp_path, roots, monkeypatch, failure):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)

    def unavailable(*args, **kwargs):
        raise failure

    unsupported = isinstance(failure, NotImplementedError) or failure.errno in (
        errno.ENOSYS,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    )
    monkeypatch.setattr(os, "link", unavailable)
    for _ in range(2):
        with pytest.raises(SandboxError if unsupported else OSError) as caught:
            await store.aput(source)
        if unsupported:
            assert "requires filesystem hard links" in str(caught.value)
            assert caught.value.__cause__ is failure
        else:
            assert caught.value is failure
        with pytest.raises(SandboxError if unsupported else OSError) as caught:
            async with store.aopen_archive(reference):
                pytest.fail("failed lease must not yield")
        if unsupported:
            assert "requires filesystem hard links" in str(caught.value)
            assert caught.value.__cause__ is failure
        else:
            assert caught.value is failure
        assert list(store.root.iterdir()) == [store.root / reference.sha256]


@pytest.mark.parametrize("stage", ["open", "fsync"])
@pytest.mark.parametrize(
    "failure",
    [
        NotImplementedError(),
        OSError(errno.ENOSYS, "unavailable"),
        OSError(errno.ENOTSUP, "unsupported"),
        OSError(errno.EOPNOTSUPP, "unsupported"),
        PermissionError(errno.EACCES, "denied"),
        OSError(errno.ENOSPC, "full"),
        OSError(errno.EIO, "I/O failure"),
    ],
)
def test_directory_sync_capability_errors_preserve_other_failures(tmp_path, monkeypatch, stage, failure):
    descriptors = []
    real_open = os.open

    def open_directory(*args, **kwargs):
        if stage == "open":
            raise failure
        descriptor = real_open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    def unavailable(*args, **kwargs):
        raise failure

    unsupported = isinstance(failure, NotImplementedError) or failure.errno in (
        errno.ENOSYS,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    )
    monkeypatch.setattr(os, "open", open_directory)
    monkeypatch.setattr(os, "fsync", unavailable)
    for _ in range(2):
        with pytest.raises(SandboxError if unsupported else OSError) as caught:
            checkpoint_module._fsync_directory(tmp_path)
        if unsupported:
            assert "requires directory fsync" in str(caught.value)
            assert caught.value.__cause__ is failure
        else:
            assert caught.value is failure
        for descriptor in descriptors:
            with pytest.raises(OSError) as closed:
                os.fstat(descriptor)
            assert closed.value.errno == errno.EBADF


def test_a_hardlink_cannot_carry_out_an_excluded_credential(tmp_path, roots):
    os.link(roots["native"] / "auth.json", roots["native"] / "session-cache")
    with pytest.raises(SandboxError, match="hardlink to excluded"):
        capture(tmp_path, roots)
    assert not (tmp_path / "checkpoint.tar").exists()


def test_an_exclusion_that_leaves_its_root_excludes_nothing_inside_it(tmp_path, roots):
    outside = tmp_path / "outside"
    outside.mkdir()
    bait = outside / "bait"
    bait.write_text("bait")
    os.link(bait, outside / "bait-alias")
    os.link(bait, roots["workspace"] / "innocent")
    (roots["native"] / "cache").symlink_to(outside)
    # Excluding the link itself stops capture rejecting it, so the exclusion scan alone
    # decides the outcome: it must not follow the link out of the root and treat what it
    # finds there as excluded content.
    archive = tmp_path / "checkpoint.tar"
    CheckpointArchive().capture(roots, archive, state={}, exclude=["native/cache", "native/cache/bait"])
    with tarfile.open(archive) as opened:
        assert "workspace/innocent" in opened.getnames()


def test_restore_applies_the_recorded_timestamps(tmp_path, roots):
    stamp = 1000000000
    for path in (roots["workspace"] / "tracked.py", roots["native"] / "transcript.jsonl", roots["workspace"]):
        os.utime(path, (stamp, stamp))
    os.utime(roots["workspace"] / "link", (stamp, stamp), follow_symlinks=False)
    destination = tmp_path / "restored"
    CheckpointArchive().restore(capture(tmp_path, roots), destination)
    assert int((destination / "workspace/tracked.py").stat().st_mtime) == stamp
    assert int((destination / "native/transcript.jsonl").stat().st_mtime) == stamp
    assert int((destination / "workspace").stat().st_mtime) == stamp
    assert int((destination / "workspace/link").lstat().st_mtime) == stamp


def test_failed_capture_removes_partial_archive(tmp_path, roots):
    (roots["workspace"] / "outside").symlink_to("../../etc/passwd")
    with pytest.raises(SandboxError, match="symlink"):
        capture(tmp_path, roots)
    assert not (tmp_path / "checkpoint.tar").exists()


def test_capture_does_not_remove_an_existing_destination(tmp_path, roots):
    path = tmp_path / "checkpoint.tar"
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        capture(tmp_path, roots)
    assert path.read_bytes() == b"existing"


def test_capture_must_not_include_itself(tmp_path, roots):
    with pytest.raises(SandboxError, match="inside"):
        CheckpointArchive().capture(roots, roots["workspace"] / "checkpoint.tar", state={})


def test_capture_limits_cleanup_partial_files(tmp_path, roots):
    archive = CheckpointArchive(CheckpointLimits(max_bytes=100))
    with pytest.raises(SandboxError, match="limit"):
        archive.capture(roots, tmp_path / "limited.tar", state={})
    assert not (tmp_path / "limited.tar").exists()


def test_corrupt_or_missing_object_is_not_restored(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    path = store.root / reference.sha256
    path.chmod(0o600)
    with path.open("r+b") as stream:
        stream.write(b"corrupt")
    with pytest.raises(SandboxError, match="checksum"):
        store.restore(reference, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    path.unlink()
    with pytest.raises(CheckpointObjectNotFound) as absent:
        store.verify(reference)
    assert isinstance(absent.value.__cause__, FileNotFoundError)


def test_object_size_and_upload_cleanup(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects", max_bytes=10)
    with pytest.raises(SandboxError, match="limit"):
        store.put(capture(tmp_path, roots))
    assert list(store.root.iterdir()) == []


def test_existing_corrupt_object_is_not_overwritten(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)
    path = store.root / reference.sha256
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    with pytest.raises(SandboxError, match="size"):
        store.put(source)
    assert path.read_bytes() == b"corrupt"
    assert not list(store.root.glob(".upload-*"))


def malicious_archive(tmp_path, members, manifest=None):
    path = tmp_path / "malicious.tar"
    with tarfile.open(path, "w") as archive:
        if manifest is None:
            manifest = json.dumps({"version": 1, "state": {}}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
        for root in ("workspace", "native"):
            info = tarfile.TarInfo(root)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        for name, kind, target in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = target
            if kind == tarfile.REGTYPE:
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            else:
                archive.addfile(info)
    return path


@pytest.mark.parametrize(
    "members",
    [
        [("../escape", tarfile.REGTYPE, "")],
        [("/workspace/absolute", tarfile.REGTYPE, "")],
        [("workspace/../escape", tarfile.REGTYPE, "")],
        [("workspace/escape", tarfile.SYMTYPE, "../../escape")],
        [("workspace/escape", tarfile.SYMTYPE, "/tmp"), ("workspace/escape/child", tarfile.REGTYPE, "")],
        [("workspace/escape", tarfile.SYMTYPE, "../native/transcript")],
        [("workspace/hardlink", tarfile.LNKTYPE, "manifest.json")],
        [("workspace/fifo", tarfile.FIFOTYPE, "")],
        [("workspace/device", tarfile.CHRTYPE, "")],
        [("workspace/dup", tarfile.REGTYPE, ""), ("workspace/dup", tarfile.REGTYPE, "")],
        [("workspace/link", tarfile.SYMTYPE, "target"), ("workspace/link/child", tarfile.REGTYPE, "")],
        [("workspace/missing/child", tarfile.REGTYPE, "")],
        [("other/file", tarfile.REGTYPE, "")],
    ],
)
def test_unsafe_archives_never_expose_partial_restore(tmp_path, members):
    path = malicious_archive(tmp_path, members)
    with pytest.raises(SandboxError):
        CheckpointArchive().restore(path, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()
    assert not list(tmp_path.glob(".restore-*"))
    assert not (tmp_path / "escape").exists()


def timestamped_archive(tmp_path, *, mtime=None, pax=None):
    path = tmp_path / "timestamped.tar"
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
        manifest = json.dumps({"version": 1, "state": {}}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
        for root in ("workspace", "native"):
            info = tarfile.TarInfo(root)
            info.type = tarfile.DIRTYPE
            info.mode = 0o700
            archive.addfile(info)
        info = tarfile.TarInfo("workspace/file")
        info.size = 1
        info.mode = 0o600
        if mtime is not None:
            info.mtime = mtime
        if pax is not None:
            info.pax_headers.update(pax)
        archive.addfile(info, io.BytesIO(b"x"))
    return path


@pytest.mark.parametrize("fields", [{"mtime": 2**64}, {"pax": {"mtime": "nan"}}])
def test_a_timestamp_the_platform_cannot_store_is_rejected(tmp_path, fields):
    path = timestamped_archive(tmp_path, **fields)
    with pytest.raises(SandboxError, match="timestamp"):
        CheckpointArchive().restore(path, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()
    assert not list(tmp_path.glob(".restore-*"))


def test_a_failed_rename_surfaces_its_cause_and_leaves_no_temporary_tree(tmp_path, roots, monkeypatch):
    locked = roots["workspace"] / "locked"
    locked.mkdir()
    (locked / "data.txt").write_text("payload")
    locked.chmod(0o500)
    source = capture(tmp_path, roots)
    locked.chmod(0o700)

    def refuse(*args, **kwargs):
        raise OSError(errno.ENOTEMPTY, "destination not empty")

    monkeypatch.setattr(os, "rename", refuse)
    with pytest.raises(OSError, match="destination not empty"):
        CheckpointArchive().restore(source, tmp_path / "restored")
    assert not list(tmp_path.glob(".restore-*"))


def test_a_rejected_restore_never_chmods_outside_its_own_tree(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    sentinel.chmod(0o755)
    # Every target normalizes back inside workspace, so these pass the per-link check and
    # only chain resolution rejects them. Cleanup then walks links that resolve above the
    # staged tree, and must not follow them.
    path = malicious_archive(
        tmp_path,
        [
            ("workspace/a", tarfile.SYMTYPE, "."),
            ("workspace/b", tarfile.SYMTYPE, "a/.."),
            ("workspace/c", tarfile.SYMTYPE, "b/.."),
            ("workspace/d", tarfile.SYMTYPE, "c/sentinel"),
        ],
    )
    with pytest.raises(SandboxError):
        CheckpointArchive().restore(path, tmp_path / "destination")
    assert sentinel.stat().st_mode & 0o777 == 0o755
    assert not list(tmp_path.glob(".restore-*"))


def test_restore_never_overwrites_current_workspace(tmp_path, roots):
    source = capture(tmp_path, roots)
    with pytest.raises(FileExistsError):
        CheckpointArchive().restore(source, roots["workspace"])
    assert (roots["workspace"] / "tracked.py").read_text() == "print('hello')"


@pytest.mark.asyncio
async def test_async_capture_concurrent_upload_and_restore(tmp_path, roots):
    archive = CheckpointArchive()
    source = tmp_path / "checkpoint.tar"
    await archive.acapture(roots, source, state={"run_id": "r"})
    first, second = FileCheckpointStore(tmp_path / "objects"), FileCheckpointStore(tmp_path / "objects")
    refs = await asyncio.gather(first.aput(source), second.aput(source))
    assert refs[0] == refs[1]
    assert await second.averify(refs[0]) is None
    assert await second.arestore(refs[0], tmp_path / "restored") == {"run_id": "r"}


@pytest.mark.asyncio
async def test_async_cancel_drains_write_before_returning(tmp_path, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    entered, release = threading.Event(), threading.Event()
    finished = []

    def slow_put(source):
        entered.set()
        release.wait(timeout=5)
        finished.append(True)
        return CheckpointRef(hashlib.sha256(b"x").hexdigest(), 1)

    monkeypatch.setattr(store, "put", slow_put)
    task = asyncio.create_task(store.aput(Path("unused")))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished == [True]


def test_composed_symlink_escape_is_rejected(tmp_path):
    source = malicious_archive(
        tmp_path,
        [
            ("workspace/a", tarfile.SYMTYPE, "."),
            ("workspace/b", tarfile.SYMTYPE, "a/../native"),
        ],
    )
    with pytest.raises(SandboxError, match="chain escapes"):
        CheckpointArchive().restore(source, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_symlink_cycle_is_rejected(tmp_path):
    source = malicious_archive(tmp_path, [("workspace/a", tarfile.SYMTYPE, "b"), ("workspace/b", tarfile.SYMTYPE, "a")])
    with pytest.raises(SandboxError, match="cycle"):
        CheckpointArchive().restore(source, tmp_path / "restored")


def test_oversized_pax_headers_are_rejected_before_parsing(tmp_path):
    source = tmp_path / "large-pax.tar"
    with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo("workspace/file")
        info.pax_headers = {"comment": "x" * 2000}
        archive.addfile(info)
    with pytest.raises(SandboxError, match="extension metadata"):
        CheckpointArchive(CheckpointLimits(max_manifest_bytes=1000)).restore(source, tmp_path / "restored")


def test_restore_does_not_depend_on_how_the_destination_is_spelled(tmp_path, roots):
    source = capture(tmp_path, roots)
    real = tmp_path / "store"
    real.mkdir()
    (tmp_path / "store-alias").symlink_to(real)
    (tmp_path / "root-alias").symlink_to(tmp_path)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)

    parents = (real, tmp_path / "store-alias", tmp_path / "root-alias" / "store")
    for index, parent in enumerate(parents):
        destination = parent / f"restored{index}"
        assert store.restore(reference, destination) == {"run_id": "r", "native_id": "n", "conversation": ["hello"]}
        assert (destination / "workspace/tracked.py").read_text() == "print('hello')"
        assert os.readlink(destination / "workspace/link") == "tracked.py"
        assert (destination / "workspace/link").read_text() == "print('hello')"
        assert (destination / "workspace/untracked").read_bytes() == bytes(range(256))

    # An alias must not buy a symlink its way out of the root either.
    escape = malicious_archive(tmp_path, [("workspace/escape", tarfile.SYMTYPE, "../native/transcript")])
    with pytest.raises(SandboxError, match="escapes"):
        CheckpointArchive().restore(escape, tmp_path / "store-alias" / "rejected")
    assert not (real / "rejected").exists()
    assert not list(real.glob(".restore-*"))


@pytest.mark.parametrize("links", [(("a", "a"),), (("a", "b"), ("b", "a"))])
def test_capture_rejects_cyclic_symlinks(tmp_path, roots, links):
    for name, target in links:
        (roots["workspace"] / name).symlink_to(target)
    with pytest.raises(SandboxError, match="cycle"):
        capture(tmp_path, roots)
    assert not (tmp_path / "checkpoint.tar").exists()


def test_dangling_links_survive_capture_and_restore(tmp_path, roots):
    (roots["workspace"] / "dangling").symlink_to("never-written.txt")
    source = capture(tmp_path, roots)
    destination = tmp_path / "restored"
    CheckpointArchive().restore(source, destination)
    assert os.readlink(destination / "workspace/dangling") == "never-written.txt"
    assert not (destination / "workspace/dangling").exists()


def virtualenv(workspace):
    """The interpreter links ``python -m venv`` makes on Linux: absolute, with relative aliases."""
    bin_dir = workspace / ".venv/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").symlink_to("/usr/local/bin/python3")
    (bin_dir / "python").symlink_to("python3")
    (workspace / ".venv/lib").mkdir()
    (workspace / ".venv/lib64").symlink_to("lib")


def test_virtualenv_interpreter_links_are_captured_verbatim(tmp_path, roots):
    virtualenv(roots["workspace"])
    source = capture(tmp_path, roots)
    with tarfile.open(source) as archive:
        links = {member.name: member.linkname for member in archive if member.issym()}
    assert links["workspace/.venv/bin/python3"] == "/usr/local/bin/python3"
    assert links["workspace/.venv/bin/python"] == "python3"
    assert CheckpointArchive().validate(source)["run_id"] == "r"


def test_validate_accepts_relative_links_that_lead_to_an_absolute_one(tmp_path):
    source = malicious_archive(
        tmp_path,
        [
            ("workspace/bin", tarfile.DIRTYPE, ""),
            ("workspace/bin/python3", tarfile.SYMTYPE, "/usr/local/bin/python3"),
            ("workspace/bin/python", tarfile.SYMTYPE, "python3"),
            ("workspace/bin/python3.12", tarfile.SYMTYPE, "python"),
        ],
    )
    assert CheckpointArchive().validate(source) == {}


def test_restore_inside_the_computer_recreates_absolute_links(tmp_path, roots):
    virtualenv(roots["workspace"])
    destination = tmp_path / "restored"
    CheckpointArchive().restore(capture(tmp_path, roots), destination, absolute_links=True)
    assert os.readlink(destination / "workspace/.venv/bin/python3") == "/usr/local/bin/python3"
    assert os.readlink(destination / "workspace/.venv/bin/python") == "python3"
    assert os.readlink(destination / "workspace/.venv/lib64") == "lib"


def test_host_restore_never_materializes_a_link_to_an_absolute_path(tmp_path, roots):
    secret = tmp_path / "host-secret"
    secret.write_text("host credential")
    (roots["workspace"] / "report.txt").symlink_to(secret)
    (roots["workspace"] / "alias.txt").symlink_to("report.txt")
    virtualenv(roots["workspace"])
    destination = tmp_path / "restored"
    CheckpointArchive().restore(capture(tmp_path, roots), destination)
    assert not os.path.lexists(destination / "workspace/report.txt")
    assert not os.path.lexists(destination / "workspace/.venv/bin/python3")
    # A relative alias of one stays a link inside the root that leads nowhere.
    assert os.readlink(destination / "workspace/alias.txt") == "report.txt"
    assert not (destination / "workspace/alias.txt").exists()
    assert (destination / "workspace/tracked.py").read_text() == "print('hello')"


def test_capture_never_follows_a_link_to_an_absolute_path(tmp_path, roots):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("host credential")
    (roots["workspace"] / "escape").symlink_to(outside)
    source = capture(tmp_path, roots, compress=False)
    with tarfile.open(source) as archive:
        names = archive.getnames()
    assert "workspace/escape" in names
    assert not any(name.startswith("workspace/escape/") for name in names)
    assert b"host credential" not in source.read_bytes()


@pytest.mark.parametrize(
    ("prepare", "limits"),
    [
        (lambda roots: os.mkfifo(roots["workspace"] / "pipe"), CheckpointLimits()),
        (lambda roots: (roots["workspace"] / "up").symlink_to("../native/transcript.jsonl"), CheckpointLimits()),
        (lambda roots: os.link(roots["native"] / "auth.json", roots["workspace"] / "copy"), CheckpointLimits()),
        (lambda roots: None, CheckpointLimits(max_entries=3)),
    ],
    ids=["fifo", "escaping-link", "excluded-hardlink", "entry-limit"],
)
def test_files_that_cannot_be_checkpointed_raise_a_content_error(tmp_path, roots, prepare, limits):
    prepare(roots)
    with pytest.raises(CheckpointContentError):
        capture(tmp_path, roots, limits=limits)
    assert not (tmp_path / "checkpoint.tar").exists()


def test_archive_cut_after_the_roots_is_rejected(tmp_path, roots):
    """Cut the stream immediately after the ``workspace`` directory header: both roots
    are still declared, every workspace file is gone, and the stored digest matches
    those bytes, so nothing but the archive framing can reject it."""
    source = capture(tmp_path, roots, compress=False)
    with tarfile.open(source) as archive:
        cut = next(member.offset_data for member in archive if member.name == "workspace")
    truncated = tmp_path / "truncated.tar"
    truncated.write_bytes(source.read_bytes()[:cut])
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(truncated)
    assert store.verify(reference) is None
    with pytest.raises(SandboxError):
        store.restore(reference, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".restore-*"))


def unparsable_archive(tmp_path, roots, kind):
    if kind == "manifest is not json":
        return malicious_archive(tmp_path, [], manifest=b"{not json")
    if kind == "manifest is not utf-8":
        return malicious_archive(tmp_path, [], manifest='{"state": "caf\xe9"}'.encode("latin-1"))
    if kind == "manifest integer past the digit limit":
        limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if not limit:
            pytest.skip("this interpreter does not limit the digits of an integer")
        return malicious_archive(tmp_path, [], manifest=b'{"version": 1, "state": {"n": ' + b"9" * (limit + 1) + b"}}")
    if kind == "manifest nested past the recursion limit":
        return malicious_archive(
            tmp_path, [], manifest=b'{"version": 1, "state": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
        )
    path = tmp_path / "unparsable.tar"
    if kind == "no tar header":
        path.write_bytes(b"x" * 4096)
        return path
    source = capture(tmp_path, roots, compress=False)
    if kind == "stream stops inside a header":
        with tarfile.open(source) as archive:
            inside = max(member.offset for member in archive) + 100
        path.write_bytes(source.read_bytes()[:inside])
        return path
    # A long-name header that no member follows. The framing walk steps over it and
    # stops on the end-of-archive marker, so only tarfile's own reader rejects this.
    data = bytearray(source.read_bytes())
    while data[-512:] == b"\x00" * 512:
        del data[-512:]
    orphan = b"workspace/orphan.txt\n"
    header = tarfile.TarInfo("././@LongLink")
    header.type, header.size = tarfile.GNUTYPE_LONGNAME, len(orphan)
    data += header.tobuf(tarfile.GNU_FORMAT, "utf-8", "surrogateescape")
    data += orphan.ljust(512, b"\x00") + b"\x00" * 1024
    path.write_bytes(bytes(data))
    return path


@pytest.mark.parametrize(
    "kind",
    [
        "no tar header",
        "stream stops inside a header",
        "long-name header with no member",
        "manifest is not json",
        "manifest is not utf-8",
        "manifest integer past the digit limit",
        "manifest nested past the recursion limit",
    ],
)
def test_unparsable_archives_are_rejected_as_sandbox_errors(tmp_path, roots, kind):
    with pytest.raises(SandboxError):
        CheckpointArchive().restore(unparsable_archive(tmp_path, roots, kind), tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".restore-*"))


def hold_upload(monkeypatch, *, fail=False):
    """Hold a real upload at its fsync boundary; ``settled`` fires when the worker leaves."""
    entered, release, settled = threading.Event(), threading.Event(), threading.Event()
    real = os.fsync

    def gate(descriptor):
        if entered.is_set():
            return real(descriptor)
        entered.set()
        assert release.wait(10), "the upload gate was never released"
        try:
            if fail:
                raise OSError(errno.ENOSPC, "injected upload failure")
            return real(descriptor)
        finally:
            settled.set()

    monkeypatch.setattr(os, "fsync", gate)
    return entered, release, settled


async def deliver(task, cancels):
    for _ in range(cancels):
        task.cancel()
        await asyncio.sleep(0)
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_upload_failure_without_cancellation_still_reaches_the_caller(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    _, release, settled = hold_upload(monkeypatch, fail=True)
    release.set()
    with pytest.raises(OSError) as error:
        await store.aput(capture(tmp_path, roots))
    assert error.value.errno == errno.ENOSPC
    assert settled.is_set()
    assert not list(store.root.glob(".upload-*"))


@pytest.mark.asyncio
async def test_cancelled_upload_reports_cancellation_when_the_write_fails(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    entered, release, settled = hold_upload(monkeypatch, fail=True)
    task = asyncio.create_task(store.aput(capture(tmp_path, roots)))
    assert await asyncio.to_thread(entered.wait, 10)
    await deliver(task, 1)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert settled.is_set(), "the write must settle before the caller returns"
    assert not list(store.root.glob(".upload-*"))
    assert not list(store.root.iterdir()), "a failed upload publishes nothing"


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_abandon_the_upload(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    entered, release, settled = hold_upload(monkeypatch)
    task = asyncio.create_task(store.aput(capture(tmp_path, roots)))
    assert await asyncio.to_thread(entered.wait, 10)
    await deliver(task, 3)
    assert not settled.is_set(), "the gate is still held, so the worker cannot have finished"
    assert not task.done(), "further cancellation must not detach the protected write"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert settled.is_set()
    assert not list(store.root.glob(".upload-*"))
    assert len(list(store.root.iterdir())) == 1


@pytest.mark.asyncio
async def test_retry_immediately_after_a_cancelled_upload(tmp_path, roots, monkeypatch):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    entered, release, _ = hold_upload(monkeypatch)
    task = asyncio.create_task(store.aput(source))
    assert await asyncio.to_thread(entered.wait, 10)
    await deliver(task, 2)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    reference = await store.aput(source)
    assert not list(store.root.glob(".upload-*"))
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]
    assert await store.arestore(reference, tmp_path / "recovered") == {
        "run_id": "r",
        "native_id": "n",
        "conversation": ["hello"],
    }


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_abandon_a_capture(tmp_path, roots, monkeypatch):
    destination = tmp_path / "cancelled.tar"
    entered, release, settled = threading.Event(), threading.Event(), threading.Event()
    original = tarfile.TarFile.addfile

    def gate(archive, info, fileobj=None):
        if info.name == "workspace/tracked.py" and not entered.is_set():
            entered.set()
            assert release.wait(10), "the capture gate was never released"
            try:
                return original(archive, info, fileobj)
            finally:
                settled.set()
        return original(archive, info, fileobj)

    monkeypatch.setattr(tarfile.TarFile, "addfile", gate)
    task = asyncio.create_task(CheckpointArchive().acapture(roots, destination, state={"run_id": "r"}))
    assert await asyncio.to_thread(entered.wait, 10)
    await deliver(task, 3)
    assert not settled.is_set()
    assert not task.done(), "further cancellation must not detach a half-written archive"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert settled.is_set()
    monkeypatch.undo()
    # The destination is settled either way: removed, or complete enough to restore.
    if destination.exists():
        assert CheckpointArchive().restore(destination, tmp_path / "from-cancelled") == {"run_id": "r"}


@pytest.mark.asyncio
async def test_draining_an_already_cancelled_operation_terminates():
    # Loop shutdown cancels the protected task itself. Draining one that is already
    # cancelled must simply return, so it neither spins nor replaces the caller's
    # cancellation with a second one.
    from agno.sandbox.checkpoint import _drain

    protected = asyncio.create_task(asyncio.sleep(3600))
    protected.cancel()
    await asyncio.wait({protected})
    assert protected.cancelled()
    await asyncio.wait_for(_drain(protected), 5)


def chained(error):
    """Every exception reachable from ``error`` by standard chaining.

    Cancellation reaches the caller through a task boundary, and how deep the drained
    failure sits differs by version: directly on ``__cause__`` from 3.11, one level
    further through ``__context__`` before it. Walk the chain instead of naming one.
    """
    seen, found = set(), []
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        found.append(error)
        error = error.__cause__ or error.__context__
    return found


@pytest.mark.asyncio
async def test_cancelled_upload_keeps_the_write_failure_reachable(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    entered, release, settled = hold_upload(monkeypatch, fail=True)
    task = asyncio.create_task(store.aput(capture(tmp_path, roots)))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        await deliver(task, 1)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError) as error:
        await task
    assert settled.is_set(), "the write must settle before the caller returns"

    failures = [item for item in chained(error.value) if isinstance(item, OSError)]
    assert failures, "the write failure must stay reachable from the cancellation"
    assert failures[0].errno == errno.ENOSPC
    assert "injected upload failure" in str(failures[0])
    # The failure keeps the frames where the write actually died, not a re-raise site.
    assert "os.fsync(output.fileno())" in "".join(traceback.format_tb(failures[0].__traceback__))
    rendered = "".join(traceback.format_exception(type(error.value), error.value, error.value.__traceback__))
    assert "injected upload failure" in rendered, "chained formatting must show the write failure"
    assert "CancelledError" in rendered

    assert not list(store.root.glob(".upload-*"))
    assert not list(store.root.iterdir()), "a failed upload publishes nothing"


@pytest.mark.asyncio
async def test_repeated_cancellation_keeps_the_write_failure_reachable(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    entered, release, settled = hold_upload(monkeypatch, fail=True)
    task = asyncio.create_task(store.aput(capture(tmp_path, roots)))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        await deliver(task, 3)
        assert not settled.is_set(), "the gate is still held, so the worker cannot have finished"
        assert not task.done(), "further cancellation must not detach the protected write"
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError) as error:
        await task
    assert settled.is_set()

    failures = [item for item in chained(error.value) if isinstance(item, OSError)]
    assert failures, "repeated cancellation must not erase the write failure"
    assert failures[0].errno == errno.ENOSPC
    assert "injected upload failure" in "".join(
        traceback.format_exception(type(error.value), error.value, error.value.__traceback__)
    )
    assert not list(store.root.glob(".upload-*"))
    assert not list(store.root.iterdir())


def test_capture_compresses_by_default_and_stores_plain_tar_when_disabled(tmp_path, roots):
    compressed = capture(tmp_path, roots)
    plain = capture(tmp_path / "plain", roots, compress=False)
    assert compressed.read_bytes()[:2] == b"\x1f\x8b"
    assert plain.read_bytes()[:2] != b"\x1f\x8b"
    with tarfile.open(plain, mode="r:") as archive:
        assert "manifest.json" in archive.getnames()
    assert compressed.stat().st_size < plain.stat().st_size


def test_the_stored_bytes_do_not_record_when_the_capture_ran(tmp_path, roots):
    """One tree must have one digest, or the store stops deduplicating it."""
    header = capture(tmp_path, roots).read_bytes()[:10]
    assert header[:2] == b"\x1f\x8b"
    assert header[3] & 0x08 == 0, "the header must not carry an original filename"
    assert header[4:8] == b"\x00\x00\x00\x00", "the header must not carry a capture time"


def test_two_captures_of_one_tree_dedup_to_a_single_object(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    first = capture(tmp_path, roots)
    second = tmp_path / "second.tar"
    CheckpointArchive().capture(
        roots, second, state={"run_id": "r", "native_id": "n", "conversation": ["hello"]}, exclude=["native/auth.json"]
    )
    assert first.read_bytes() == second.read_bytes()
    assert store.put(first) == store.put(second)
    assert len(list(store.root.iterdir())) == 1


@pytest.mark.parametrize("compress", [True, False])
def test_both_stored_representations_restore_the_same_tree(tmp_path, roots, compress):
    source = tmp_path / "checkpoint.tar"
    CheckpointArchive(compress=compress).capture(roots, source, state={"run_id": "r"}, exclude=["native/auth.json"])
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)
    # Digest and size describe the stored object, whichever representation that is.
    assert reference.size == source.stat().st_size
    assert reference.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / "restored"
    assert store.restore(reference, destination) == {"run_id": "r"}
    assert (destination / "workspace/untracked").read_bytes() == bytes(range(256))
    assert (destination / "workspace/tracked.py").stat().st_mode & 0o777 == 0o751
    assert os.readlink(destination / "workspace/link") == "tracked.py"
    assert not (destination / "native/auth.json").exists()


def test_a_reader_accepts_either_representation_whatever_its_own_setting(tmp_path, roots):
    """The stored format is a property of the bytes, not of the reader's default."""
    for writer, reader in ((True, False), (False, True)):
        source = tmp_path / f"written-{writer}.tar"
        CheckpointArchive(compress=writer).capture(roots, source, state={"run_id": "r"})
        destination = tmp_path / f"restored-{writer}"
        assert CheckpointArchive(compress=reader).restore(source, destination) == {"run_id": "r"}
        assert (destination / "workspace/tracked.py").read_text() == "print('hello')"
        assert (destination / "native/auth.json").read_text() == "credential"


def broken_compressed(tmp_path, roots, kind):
    path = tmp_path / "broken.tar"
    if kind == "compressed non-archive":
        path.write_bytes(gzip.compress(b"x" * 4096))
        return path
    if kind == "compressed cut archive":
        plain = capture(tmp_path, roots, compress=False).read_bytes()
        path.write_bytes(gzip.compress(plain[: len(plain) // 2]))
        return path
    data = capture(tmp_path, roots).read_bytes()
    if kind == "truncated stream":
        path.write_bytes(data[: len(data) // 2])
    elif kind == "corrupt deflate":
        middle = len(data) // 2
        path.write_bytes(data[:middle] + bytes((data[middle] ^ 0xFF,)) + data[middle + 1 :])
    else:
        path.write_bytes(data[:-4] + b"\x00\x00\x00\x00")
    return path


@pytest.mark.parametrize(
    "kind",
    ["truncated stream", "corrupt deflate", "wrong trailer", "compressed non-archive", "compressed cut archive"],
)
def test_malformed_compressed_checkpoints_are_rejected_as_sandbox_errors(tmp_path, roots, kind):
    source = broken_compressed(tmp_path, roots, kind)
    before = sorted(path.name for path in tmp_path.iterdir())
    with pytest.raises(SandboxError):
        CheckpointArchive().restore(source, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".restore-*"))
    # Expanding a compressed object must not leave a staging file behind either.
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_expansion_stops_at_the_limit_before_the_whole_archive_is_written(tmp_path, roots, monkeypatch):
    """A decompression bomb is bounded by expanded bytes; stored size bounds nothing."""
    (roots["workspace"] / "compressible").write_bytes(bytes(8 * 1024 * 1024))
    source = capture(tmp_path, roots)
    limits = CheckpointLimits(max_bytes=2 * 1024 * 1024)
    assert source.stat().st_size < limits.max_bytes, "the stored object must fit under the limit it expands past"

    written = []
    real = tempfile.TemporaryFile

    def counted(*args, **kwargs):
        handle = real(*args, **kwargs)
        write = handle.write

        def record(data):
            written.append(len(data))
            return write(data)

        handle.write = record
        return handle

    monkeypatch.setattr(tempfile, "TemporaryFile", counted)
    with pytest.raises(SandboxError, match="limit"):
        CheckpointArchive(limits).restore(source, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".restore-*"))
    assert sum(written) <= limits.max_bytes + 1024 * 1024, "expansion ran past the limit before stopping"


@pytest.mark.parametrize(
    ("members", "manifest", "message"),
    [
        ([("workspace/escape", tarfile.SYMTYPE, "../../escape")], None, "escapes"),
        ([("workspace/hardlink", tarfile.LNKTYPE, "manifest.json")], None, "unsupported"),
        ([("../escape", tarfile.REGTYPE, "")], None, "Unsafe"),
        ([], b"{not json", "manifest"),
    ],
)
def test_compressing_a_hostile_archive_does_not_get_it_past_validation(tmp_path, members, manifest, message):
    plain = malicious_archive(tmp_path, members, manifest=manifest)
    source = tmp_path / "hostile.tar"
    source.write_bytes(gzip.compress(plain.read_bytes()))
    with pytest.raises(SandboxError, match=message):
        CheckpointArchive().restore(source, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "escape").exists()
    assert not list(tmp_path.glob(".restore-*"))


@pytest.mark.asyncio
async def test_async_capture_and_restore_round_trip_compressed(tmp_path, roots):
    archive = CheckpointArchive()
    source = tmp_path / "checkpoint.tar"
    await archive.acapture(roots, source, state={"run_id": "r"})
    assert source.read_bytes()[:2] == b"\x1f\x8b"
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(source)
    # Twice: the second restore reads an object the first one already read.
    for index in range(2):
        destination = tmp_path / f"restored{index}"
        assert await store.arestore(reference, destination) == {"run_id": "r"}
        assert (destination / "workspace/tracked.py").read_text() == "print('hello')"


class MemoryCheckpointStore:
    """The smallest thing that satisfies the store contract, with no local object path.

    It stands in for a store whose objects are remote: every read materializes a
    temporary copy and removes it when the caller is done with it.
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

    async def aput(self, source):
        return self.put(source)

    def verify(self, reference):
        data = self.objects.get(reference.sha256)
        if data is None:
            raise SandboxError("Missing checkpoint object")
        if len(data) != reference.size or hashlib.sha256(data).hexdigest() != reference.sha256:
            raise SandboxError("Checkpoint checksum mismatch")

    async def averify(self, reference):
        self.verify(reference)

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

    @contextlib.asynccontextmanager
    async def aopen_archive(self, reference):
        with self.open_archive(reference) as path:
            yield path

    def delete(self, reference):
        self.objects.pop(reference.sha256, None)

    async def adelete(self, reference):
        self.delete(reference)


def test_a_minimal_store_satisfies_the_contract_its_consumers_use(tmp_path, roots):
    """Consumers must depend on the contract, not on FileCheckpointStore's filesystem."""
    for index, store in enumerate((FileCheckpointStore(tmp_path / "objects"), MemoryCheckpointStore(tmp_path / "mem"))):
        assert isinstance(store, CheckpointStore)
        reference = store.put(capture(tmp_path / f"source{index}", roots))
        with store.open_archive(reference) as source:
            state = CheckpointArchive().restore(source, tmp_path / f"restored{index}")
        assert state == {"run_id": "r", "native_id": "n", "conversation": ["hello"]}


def test_open_archive_yields_the_stored_bytes_and_keeps_the_object(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)
    with store.open_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
        assert path.stat().st_size == reference.size
    # An immutable object is store content, not a materialization: exiting the context
    # must not remove it, and a second access must still find it.
    assert (store.root / reference.sha256).exists()
    assert store.verify(reference) is None


def test_open_archive_refuses_an_object_that_does_not_match_its_reference(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    (store.root / reference.sha256).chmod(0o600)
    (store.root / reference.sha256).write_bytes(b"corrupt")
    entered = False
    with pytest.raises(SandboxError, match="size"):
        with store.open_archive(reference):
            entered = True
    assert not entered, "verification must happen before the path is handed out"


def test_open_archive_releases_after_a_consumer_exception_and_keeps_the_object(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    local = store.put(capture(tmp_path, roots))
    memory = MemoryCheckpointStore(tmp_path / "mem")
    remote = memory.put(capture(tmp_path / "source", roots))

    for implementation, reference in ((store, local), (memory, remote)):
        with pytest.raises(ZeroDivisionError):
            with implementation.open_archive(reference):
                raise ZeroDivisionError("the consumer failed")

    assert [path.name for path in store.root.iterdir()] == [local.sha256], "nothing else survives it"
    assert not any(path.exists() for path in memory.materialized), "a materialization does not"
    assert list(memory.directory.iterdir()) == []


def test_repeated_and_concurrent_access_have_independent_lifetimes(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    memory = MemoryCheckpointStore(tmp_path / "mem")
    remote = memory.put(capture(tmp_path / "source", roots))

    # Twice, because the second pass reads an object a completed access already read.
    for _ in range(2):
        with store.open_archive(reference) as outer:
            with store.open_archive(reference) as inner:
                assert inner.read_bytes() == outer.read_bytes()
            assert outer.read_bytes()[:2] == b"\x1f\x8b", "the finished access must not invalidate this one"

        with memory.open_archive(remote) as outer:
            with memory.open_archive(remote) as inner:
                assert inner != outer
                assert inner.read_bytes() == outer.read_bytes()
            assert not inner.exists(), "the inner materialization is gone"
            assert outer.exists(), "the outer materialization is not"
        assert not outer.exists()
    assert list(memory.directory.iterdir()) == []


def test_delete_removes_the_object_and_is_idempotent(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    store.delete(reference)
    assert list(store.root.iterdir()) == []
    with pytest.raises(CheckpointObjectNotFound) as absent:
        store.verify(reference)
    assert isinstance(absent.value.__cause__, FileNotFoundError)
    # Retention runs on its own schedule and can see an object twice.
    store.delete(reference)
    assert list(store.root.iterdir()) == []


def test_restore_verifies_the_object_once_for_one_access(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    hashed = []
    real = hashlib.sha256

    def counted(*args, **kwargs):
        hashed.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", counted)
    assert store.restore(reference, tmp_path / "restored") == {
        "run_id": "r",
        "native_id": "n",
        "conversation": ["hello"],
    }
    assert len(hashed) == 1, "one access hashes the object once"


@pytest.mark.asyncio
async def test_async_access_restores_and_keeps_the_object(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    for index in range(2):
        async with store.aopen_archive(reference) as source:
            assert await CheckpointArchive().arestore(source, tmp_path / f"restored{index}") == {
                "run_id": "r",
                "native_id": "n",
                "conversation": ["hello"],
            }
    assert (store.root / reference.sha256).exists()


@pytest.mark.asyncio
async def test_async_access_cleans_up_after_a_consumer_exception(tmp_path, roots):
    memory = MemoryCheckpointStore(tmp_path / "mem")
    reference = memory.put(capture(tmp_path, roots))
    with pytest.raises(ZeroDivisionError):
        async with memory.aopen_archive(reference):
            raise ZeroDivisionError("the consumer failed")
    assert list(memory.directory.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancels", [1, 3])
async def test_cancelling_an_async_access_drains_its_verification(tmp_path, roots, monkeypatch, cancels):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    entered, release, settled = threading.Event(), threading.Event(), threading.Event()
    real = checkpoint_module._regular

    def gate(path):
        entered.set()
        assert release.wait(10), "the verification gate was never released"
        try:
            return real(path)
        finally:
            settled.set()

    monkeypatch.setattr(checkpoint_module, "_regular", gate)

    async def access():
        async with store.aopen_archive(reference) as source:
            return source

    task = asyncio.create_task(access())
    assert await asyncio.to_thread(entered.wait, 5)
    await deliver(task, cancels)
    assert not task.done(), "the verification must not be abandoned mid-read"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(settled.wait, 5)
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]


# A synthetic stand-in for a credential; never a real one.
SECRET = b"synthetic-not-a-real-credential-8f21\n"


def overlapping(tmp_path, shape):
    """Roots that resolve onto one another, with the exclusion that should hide SECRET."""
    if shape == "the same directory":
        shared = tmp_path / "both"
        shared.mkdir()
        (shared / "auth.json").write_bytes(SECRET)
        return {"workspace": shared, "native": shared}, "native/auth.json"
    if shape == "native inside workspace":
        workspace = tmp_path / "ws"
        workspace.mkdir()
        native = workspace / "native"
        native.mkdir()
        (native / "auth.json").write_bytes(SECRET)
        return {"workspace": workspace, "native": native}, "native/auth.json"
    native = tmp_path / "nat"
    native.mkdir()
    workspace = native / "workspace"
    workspace.mkdir()
    (workspace / "token.json").write_bytes(SECRET)
    return {"workspace": workspace, "native": native}, "workspace/token.json"


@pytest.mark.parametrize("compress", [True, False])
@pytest.mark.parametrize("shape", ["the same directory", "native inside workspace", "workspace inside native"])
def test_overlapping_durable_roots_are_refused_before_anything_is_written(tmp_path, shape, compress):
    """An exclusion names one archive prefix, so an overlap smuggles the bytes under the other.

    Excluding native/auth.json hides that name while the same file is archived as
    workspace/native/auth.json, and the symmetric case puts an excluded workspace path
    under native/. Both orderings and both stored representations are covered here.
    """
    roots, exclusion = overlapping(tmp_path, shape)
    destination = tmp_path / "checkpoint.tar"
    with pytest.raises(SandboxError, match="overlap"):
        CheckpointArchive(compress=compress).capture(roots, destination, state={"run_id": "r"}, exclude=[exclusion])
    assert not destination.exists(), "the destination was created before the roots were validated"


def test_an_ancestor_alias_cannot_disguise_overlapping_roots(tmp_path):
    """Neither root is itself a link, so the existing symlink check does not see this."""
    workspace = tmp_path / "real" / "ws"
    workspace.mkdir(parents=True)
    native = workspace / "native"
    native.mkdir()
    (native / "auth.json").write_bytes(SECRET)
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    aliased = tmp_path / "alias" / "ws" / "native"
    assert not aliased.is_symlink() and not workspace.is_symlink()
    with pytest.raises(SandboxError, match="overlap"):
        CheckpointArchive().capture(
            {"workspace": workspace, "native": aliased},
            tmp_path / "checkpoint.tar",
            state={},
            exclude=["native/auth.json"],
        )
    assert not (tmp_path / "checkpoint.tar").exists()


@pytest.mark.parametrize("compress", [True, False])
def test_disjoint_sibling_roots_still_capture_and_exclude(tmp_path, roots, compress):
    source = capture(tmp_path / f"ok{compress}", roots, compress=compress)
    store = FileCheckpointStore(tmp_path / "objects")
    destination = tmp_path / f"restored{compress}"
    assert store.restore(store.put(source), destination) == {
        "run_id": "r",
        "native_id": "n",
        "conversation": ["hello"],
    }
    assert (destination / "workspace/tracked.py").read_text() == "print('hello')"
    assert (destination / "native/transcript.jsonl").exists()
    assert not (destination / "native/auth.json").exists()


def test_roots_that_merely_share_a_name_prefix_are_not_overlapping(tmp_path):
    """work and workspace-two share a prefix as strings but neither contains the other."""
    first, second = tmp_path / "work", tmp_path / "workspace-two"
    for path in (first, second):
        path.mkdir()
    (first / "app.py").write_text("print(1)")
    (second / "thread.jsonl").write_text("{}\n")
    destination = tmp_path / "checkpoint.tar"
    CheckpointArchive().capture({"workspace": first, "native": second}, destination, state={"run_id": "r"})
    assert CheckpointArchive().restore(destination, tmp_path / "restored") == {"run_id": "r"}
    assert (tmp_path / "restored/workspace/app.py").read_text() == "print(1)"
    assert (tmp_path / "restored/native/thread.jsonl").read_text() == "{}\n"


def vanished(tmp_path, roots):
    """A valid reference whose object retention, storage loss or deletion removed."""
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path / "src", roots))
    (store.root / reference.sha256).unlink()
    return store, reference


def test_a_missing_object_is_a_store_error_through_every_sync_access(tmp_path, roots):
    store, reference = vanished(tmp_path, roots)
    with pytest.raises(CheckpointObjectNotFound):
        store.verify(reference)
    with pytest.raises(CheckpointObjectNotFound):
        with store.open_archive(reference):
            pass
    with pytest.raises(CheckpointObjectNotFound):
        store.restore(reference, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.asyncio
async def test_a_missing_object_is_a_store_error_through_every_async_access(tmp_path, roots):
    store, reference = vanished(tmp_path, roots)
    with pytest.raises(CheckpointObjectNotFound):
        await store.averify(reference)
    with pytest.raises(CheckpointObjectNotFound):
        async with store.aopen_archive(reference):
            pass
    with pytest.raises(CheckpointObjectNotFound):
        await store.arestore(reference, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_the_missing_object_error_is_a_sandbox_error_that_keeps_its_cause(tmp_path, roots):
    """Consumers catching SandboxError keep working; the filesystem detail is not lost."""
    store, reference = vanished(tmp_path, roots)
    with pytest.raises(SandboxError) as caught:
        store.verify(reference)
    assert isinstance(caught.value, CheckpointObjectNotFound)
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert caught.value.__cause__.filename == str(store.root / reference.sha256)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the mode this test relies on")
def test_an_unreadable_object_stays_a_permission_error(tmp_path, roots):
    """Only the missing case is translated; other filesystem failures stay themselves."""
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path / "src", roots))
    path = store.root / reference.sha256
    path.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            store.verify(reference)
        with pytest.raises(PermissionError):
            store.restore(reference, tmp_path / "restored")
    finally:
        path.chmod(0o600)
    assert store.verify(reference) is None


def test_corrupt_and_oversized_objects_keep_their_existing_errors(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path / "src", roots))
    path = store.root / reference.sha256
    original = path.read_bytes()
    damaged = bytearray(original)
    damaged[len(damaged) // 2] ^= 0xFF
    path.chmod(0o600)
    path.write_bytes(bytes(damaged))
    with pytest.raises(SandboxError, match="checksum") as caught:
        store.verify(reference)
    assert not isinstance(caught.value, CheckpointObjectNotFound)
    path.write_bytes(original + b"extra")
    with pytest.raises(SandboxError, match="size") as caught:
        store.verify(reference)
    assert not isinstance(caught.value, CheckpointObjectNotFound)
    path.write_bytes(original)
    small = FileCheckpointStore(store.root, max_bytes=reference.size - 1)
    with pytest.raises(SandboxError, match="limit") as caught:
        small.verify(reference)
    assert not isinstance(caught.value, CheckpointObjectNotFound)


@pytest.mark.asyncio
async def test_deleting_an_absent_object_is_still_successful(tmp_path, roots):
    store, reference = vanished(tmp_path, roots)
    assert store.delete(reference) is None
    assert await store.adelete(reference) is None
    assert list(store.root.iterdir()) == []


def oversized(roots, shape):
    """A tree whose expanded tar stream is far larger than its compressed object."""
    if shape == "one padded file":
        (roots["workspace"] / "padding").write_bytes(bytes(99_000))
    else:
        for index in range(200):
            (roots["workspace"] / f"empty{index}").write_bytes(b"")


@pytest.mark.parametrize("shape", ["one padded file", "two hundred empty files"])
@pytest.mark.parametrize("compress", [True, False])
def test_a_capture_cannot_exceed_the_limit_its_own_restore_applies(tmp_path, roots, shape, compress):
    """Restore bounds the expanded tar stream, so capture has to bound the same bytes.

    Entry framing and the end-of-archive padding are part of that stream, and a
    compressed object's own size bounds none of it. Without this, capture publishes a
    checkpoint that restore can never read back.
    """
    oversized(roots, shape)
    destination = tmp_path / "checkpoint.tar"
    with pytest.raises(SandboxError, match="limit"):
        CheckpointArchive(CheckpointLimits(max_bytes=100_000), compress=compress).capture(roots, destination, state={})
    assert not destination.exists()


@pytest.mark.parametrize("compress", [True, False])
def test_the_limit_admits_an_archive_whose_expanded_stream_exactly_fits(tmp_path, roots, compress):
    """The bound is that stream's real length, not a conservative allowance for it."""
    stored = capture(tmp_path / "reference", roots, compress=compress).read_bytes()
    limits = CheckpointLimits(max_bytes=len(gzip.decompress(stored) if compress else stored))
    destination = capture(tmp_path / "exact", roots, compress=compress, limits=limits)
    assert CheckpointArchive(limits).restore(destination, tmp_path / "restored")["run_id"] == "r"


def test_an_opened_object_stays_readable_while_retention_deletes_it(tmp_path, roots):
    """The path an access hands out stays valid for the whole context.

    Retention runs on its own schedule, so it can remove the object while a consumer
    holds it. One that already passed verification must not then fail to read.
    """
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    with store.open_archive(reference) as path:
        store.delete(reference)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
        assert CheckpointArchive().restore(path, tmp_path / "restored")["run_id"] == "r"
    assert not path.exists(), "what the access held is released with the context"
    assert list(store.root.iterdir()) == []


@pytest.mark.asyncio
async def test_an_async_access_stays_readable_while_retention_deletes_its_object(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    async with store.aopen_archive(reference) as path:
        await store.adelete(reference)
        assert await CheckpointArchive().arestore(path, tmp_path / "restored") == {
            "run_id": "r",
            "native_id": "n",
            "conversation": ["hello"],
        }
    assert not path.exists()
    assert list(store.root.iterdir()) == []


def test_a_restore_survives_retention_deleting_the_object_after_verification(tmp_path, roots, monkeypatch):
    """The in-repo consumer: ``restore`` opens the path once verification succeeded."""
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    real = CheckpointArchive.restore

    def delete_first(self, source, destination):
        store.delete(reference)
        return real(self, source, destination)

    monkeypatch.setattr(CheckpointArchive, "restore", delete_first)
    assert store.restore(reference, tmp_path / "restored")["run_id"] == "r"
    assert list(store.root.iterdir()) == []


@contextlib.contextmanager
def after_lease(step):
    """Run ``step(leased_path)`` at the one point an access holds its lease and has done nothing else.

    Scoped to the access: ``put`` links its upload into place as well, and must not trigger it.
    """
    real = os.link

    def link(source, target, *args, **kwargs):
        real(source, target, *args, **kwargs)
        step(Path(target))

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(os, "link", link)
        yield


def deleted_when_leased(store, reference):
    return after_lease(lambda leased: store.delete(reference))


def test_an_access_survives_retention_deleting_the_object_the_moment_it_is_leased(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    # Twice, because the second pass starts from what the first one left behind.
    for index in range(2):
        reference = store.put(source)
        with deleted_when_leased(store, reference), store.open_archive(reference) as path:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
            assert CheckpointArchive().restore(path, tmp_path / f"restored{index}")["run_id"] == "r"
        assert list(store.root.iterdir()) == []


@pytest.mark.asyncio
async def test_an_async_access_survives_retention_deleting_the_object_the_moment_it_is_leased(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    for index in range(2):
        reference = await store.aput(source)
        with deleted_when_leased(store, reference):
            async with store.aopen_archive(reference) as path:
                assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
                assert (await CheckpointArchive().arestore(path, tmp_path / f"restored{index}"))["run_id"] == "r"
        assert list(store.root.iterdir()) == []


# The tests below split the canonical name from the leased one. Retention and a store are not
# expected to rewrite an immutable object, so these are mechanism tests: they show which file
# an access verifies and hands out, not that a replacement race occurs in production.


def replace_canonical(store, reference, content):
    """Give the canonical name different bytes under a new inode; any lease keeps the old one."""
    canonical = store.root / reference.sha256
    canonical.unlink()
    canonical.write_bytes(content)


def corrupt_in_place(path):
    # Stored objects are read-only; corruption from outside the store lifts that first.
    path.chmod(0o600)
    with path.open("r+b") as stream:
        first = stream.read(1)
        stream.seek(0)
        stream.write(bytes([first[0] ^ 0xFF]))


def test_an_access_verifies_the_file_it_yields_not_the_canonical_name(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    opened, real = [], checkpoint_module._regular

    def spy(path):
        opened.append(Path(path))
        return real(path)

    monkeypatch.setattr(checkpoint_module, "_regular", spy)
    with store.open_archive(reference) as path:
        assert path != store.root / reference.sha256
        assert opened == [path], "the only file opened to verify is the one handed out"


@pytest.mark.asyncio
async def test_an_async_access_verifies_the_file_it_yields_not_the_canonical_name(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    opened, real = [], checkpoint_module._regular

    def spy(path):
        opened.append(Path(path))
        return real(path)

    monkeypatch.setattr(checkpoint_module, "_regular", spy)
    async with store.aopen_archive(reference) as path:
        assert path != store.root / reference.sha256
        assert opened == [path]


def test_a_leased_object_whose_bytes_changed_is_refused_and_its_lease_released(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(source)
    good = (store.root / reference.sha256).read_bytes()

    def damage(leased):
        replace_canonical(store, reference, good)  # the canonical name is intact, the lease is not
        corrupt_in_place(leased)

    entered = False
    with after_lease(damage):
        with pytest.raises(SandboxError, match="checksum"):
            with store.open_archive(reference):
                entered = True
    assert not entered, "a failed verification never yields a path"
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]
    # Repeated use of the same store: the failure left nothing that blocks the next access.
    with store.open_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]


@pytest.mark.asyncio
async def test_a_leased_async_object_whose_bytes_changed_is_refused_and_its_lease_released(tmp_path, roots):
    source = capture(tmp_path, roots)
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(source)
    good = (store.root / reference.sha256).read_bytes()

    def damage(leased):
        replace_canonical(store, reference, good)
        corrupt_in_place(leased)

    entered = False
    with after_lease(damage):
        with pytest.raises(SandboxError, match="checksum"):
            async with store.aopen_archive(reference):
                entered = True
    assert not entered
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]
    async with store.aopen_archive(reference) as path:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]


def test_an_intact_lease_is_accepted_whatever_the_canonical_name_now_holds(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = store.put(capture(tmp_path, roots))
    with after_lease(lambda leased: replace_canonical(store, reference, b"not the checkpoint")):
        with store.open_archive(reference) as path:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]


@pytest.mark.asyncio
async def test_an_intact_async_lease_is_accepted_whatever_the_canonical_name_now_holds(tmp_path, roots):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    with after_lease(lambda leased: replace_canonical(store, reference, b"not the checkpoint")):
        async with store.aopen_archive(reference) as path:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == reference.sha256
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancels", [1, 3])
async def test_a_cancelled_async_access_holds_its_lease_until_verification_has_drained(
    tmp_path, roots, monkeypatch, cancels
):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    entered, release = threading.Event(), threading.Event()
    real = checkpoint_module._regular

    def gate(path):
        entered.set()
        assert release.wait(10), "the verification gate was never released"
        return real(path)

    monkeypatch.setattr(checkpoint_module, "_regular", gate)

    async def access():
        async with store.aopen_archive(reference) as source:
            return source

    task = asyncio.create_task(access())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await deliver(task, cancels)
        assert not task.done(), "the verification must not be abandoned mid-read"
        held = [path.name for path in store.root.iterdir() if path.name != reference.sha256]
        assert len(held) == 1, "the lease is still held while the verification thread still uses it"
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]
    async with store.aopen_archive(reference) as path:  # the cancelled access left the store usable
        assert path.exists()


@pytest.mark.asyncio
async def test_a_cancelled_async_access_keeps_the_verification_failure_reachable(tmp_path, roots, monkeypatch):
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(capture(tmp_path, roots))
    corrupt_in_place(store.root / reference.sha256)
    entered, release = threading.Event(), threading.Event()
    real = checkpoint_module._regular

    def gate(path):
        entered.set()
        assert release.wait(10), "the verification gate was never released"
        return real(path)

    monkeypatch.setattr(checkpoint_module, "_regular", gate)
    reached = False

    async def access():
        nonlocal reached
        async with store.aopen_archive(reference):
            reached = True

    task = asyncio.create_task(access())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await deliver(task, 1)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError) as error:
        await task
    assert not reached
    failures = [item for item in chained(error.value) if isinstance(item, SandboxError)]
    assert failures and "checksum" in str(failures[0]), "the failure that died under the cancellation stays reachable"
    assert [path.name for path in store.root.iterdir()] == [reference.sha256]
