"""Portable checkpoint archives and immutable storage outside sandbox compute.

Callers must drain the harness and quiesce workspace writers before capture.
Filesystem checkpoints do not capture processes or undo external side effects.
"""

from __future__ import annotations

import asyncio
import errno
import gzip
import hashlib
import io
import json
import os
import posixpath
import shutil
import stat
import tarfile
import tempfile
import zlib
from contextlib import asynccontextmanager, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    BinaryIO,
    Callable,
    ContextManager,
    Dict,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    TypeVar,
    runtime_checkable,
)

from agno.sandbox.base import SandboxError

_ROOTS = {"workspace", "native"}
_MANIFEST = "manifest.json"
_CHUNK = 1024 * 1024
_GZIP_MAGIC = b"\x1f\x8b"
# Level 4, not zlib's default 6: on a checkpoint of already-deflated package data plus a
# source tree it reaches within 5% of 6's ratio for 44% of its time, and a capture runs
# on every turn.
_GZIP_LEVEL = 4
_T = TypeVar("_T")


async def _drain(task: asyncio.Task[Any]) -> Optional[BaseException]:
    """Let a shielded operation finish, however often the caller is cancelled.

    Shielding alone is not enough: a second cancellation interrupts the await that was
    waiting for the work, and the caller returns while it is still running. ``wait``
    reports completion without re-raising, so the operation's own failure cannot divert
    the drain either. Returning the failure retrieves it, so it is never a stray task
    exception, and lets the caller chain it onto the cancellation it is about to raise.
    """
    while not task.done():
        with suppress(asyncio.CancelledError):
            await asyncio.wait({task})
    return None if task.cancelled() else task.exception()


async def _thread(
    function: Callable[..., _T], *args: Any, release: Optional[Callable[[_T], object]] = None, **kwargs: Any
) -> _T:
    # Filesystem work cannot be stopped by cancelling its awaiter. Drain it so the
    # caller never races cleanup/retry against a still-writing background thread.
    # ``release`` frees a result that finished under the cancellation, which the caller never receives.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancelled:
        failure = await _drain(task)
        if failure is None:
            if release is not None and not task.cancelled():
                try:
                    release(task.result())
                except Exception as error:
                    # The cancellation stays the outcome; a cleanup that failed under it is
                    # chained on as the diagnostic, never raised in its place.
                    raise cancelled from error
            raise
        # Cancellation stays the outcome, but the write that died under it is still the
        # useful diagnostic, so chain it on rather than discarding it.
        raise cancelled from failure


class CheckpointObjectNotFound(SandboxError):
    """The object a reference names is not in storage.

    Retention, storage loss or an external deletion removes objects that references
    still point at. It is a condition of the storage rather than of the request, so a
    service answers it as storage being unavailable, not as a missing resource.
    """


class CheckpointContentError(SandboxError):
    """The captured files cannot be checkpointed as they stand.

    The cause is in the files themselves, such as a special file, a link that escapes
    its root or a tree over the limits, so capturing them again fails the same way.
    """


@dataclass(frozen=True)
class CheckpointRef:
    """Immutable bytes; publish this reference only after the durable run commit."""

    sha256: str
    size: int

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("Invalid checkpoint digest")
        if type(self.size) is not int or self.size < 1:
            raise ValueError("Checkpoint size must be positive")


@dataclass(frozen=True)
class CheckpointLimits:
    max_bytes: int = 1024 * 1024 * 1024
    max_entries: int = 100_000
    max_manifest_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if any(type(v) is not int or v < 1 for v in (self.max_bytes, self.max_entries, self.max_manifest_bytes)):
            raise ValueError("Checkpoint limits must be positive integers")


def _name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(p in ("", ".", "..") for p in name.split("/"))
    ):
        raise CheckpointContentError("Unsafe checkpoint path")
    if path.parts[0] not in _ROOTS and name != _MANIFEST:
        raise CheckpointContentError("Checkpoint path is outside declared roots")
    return path


def _link(name: str, target: str) -> None:
    if not target or "\\" in target or "\x00" in target:
        raise CheckpointContentError(f"Unsafe checkpoint symlink {name!r} -> {target!r}; exclude it before capture")
    # An absolute target names the computer's own filesystem, so it is kept verbatim and
    # only ever materialized inside a computer.
    if target.startswith("/"):
        return
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    if PurePosixPath(resolved).parts[0] != PurePosixPath(name).parts[0]:
        raise CheckpointContentError(
            f"Checkpoint symlink {name!r} -> {target!r} escapes its durable root; exclude it before capture"
        )


def _validate_link_graph(members: Mapping[str, tarfile.TarInfo]) -> None:
    for name, info in members.items():
        if not info.issym() or info.linkname.startswith("/"):
            continue
        root = name.split("/", 1)[0]
        pending = name.split("/")[:-1] + info.linkname.split("/")
        resolved: list[str] = []
        hops = 0
        while pending:
            part, *pending = pending
            if part in ("", "."):
                continue
            if part == "..":
                if len(resolved) <= 1:
                    raise CheckpointContentError("Checkpoint symlink chain escapes its durable root")
                resolved.pop()
                continue
            resolved.append(part)
            if resolved[0] != root:
                raise CheckpointContentError("Checkpoint symlink chain escapes its durable root")
            target = members.get("/".join(resolved))
            if target is not None and target.issym():
                if target.linkname.startswith("/"):
                    # The rest of the chain is in the computer's own filesystem.
                    break
                hops += 1
                if hops > 40:
                    raise CheckpointContentError("Checkpoint contains a symlink cycle or excessive indirection")
                resolved.pop()
                pending = target.linkname.split("/") + pending


def _resolved(path: Path) -> Path:
    """Resolve a symlink, rejecting a chain the kernel cannot follow.

    Python 3.13 stopped raising from ``resolve()`` for symlink loops, so ask for ELOOP;
    a dangling link reports ENOENT and keeps the unresolved path it points at.
    """
    try:
        os.stat(path)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise CheckpointContentError("Checkpoint contains a symlink cycle or an unfollowable chain") from error
    return path.resolve()


def _regular(path: Path) -> BinaryIO:
    if not hasattr(os, "O_NOFOLLOW"):
        raise SandboxError("Checkpoint file access requires os.O_NOFOLLOW; use a host with no-follow file opens")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise SandboxError("Checkpoint object must be a regular file")
    return os.fdopen(fd, "rb")


def _encoder(output: BinaryIO, compress: bool) -> ContextManager[Any]:
    """Wrap a destination file in the configured encoder, for writers of either format.

    The yielded sink is writable binary either way, but ``GzipFile`` and the plain file
    share no stream supertype that typeshed declares, hence ``Any``.

    No filename and no timestamp go in the header: the store deduplicates objects by
    the digest of their stored bytes, and recording when a capture ran would give one
    unchanged tree a different object every turn.
    """
    if not compress:
        return nullcontext(output)
    return gzip.GzipFile(filename="", mode="wb", compresslevel=_GZIP_LEVEL, fileobj=output, mtime=0)


@contextmanager
def _archive_bytes(source: Path, limits: CheckpointLimits) -> Iterator[BinaryIO]:
    """Open a stored checkpoint object as a seekable stream of archive bytes.

    Both stored representations are accepted, identified by the compressed one's two
    magic bytes rather than by trying decoders in turn. Validation walks tar offsets, so
    compressed bytes are expanded into a real descriptor before any of them is trusted.
    The expansion is chunked and counted: a stored size bounds nothing once the bytes are
    deflated, so the limit has to be applied as they are produced. The staging file is
    unlinked as it is created, so an interrupted restore leaves nothing to clean up.
    """
    with _regular(source) as stored:
        if os.fstat(stored.fileno()).st_size > limits.max_bytes:
            raise SandboxError("Checkpoint archive exceeds its limit")
        magic = stored.read(len(_GZIP_MAGIC))
        stored.seek(0)
        if magic != _GZIP_MAGIC:
            yield stored
            return
        with tempfile.TemporaryFile() as expanded:
            total = 0
            with gzip.GzipFile(fileobj=stored, mode="rb") as decoder:
                while True:
                    # Only the decode is guarded. A write failure here is a real
                    # filesystem error and has to reach the caller as one.
                    try:
                        chunk = decoder.read(_CHUNK)
                    except (EOFError, zlib.error, gzip.BadGzipFile) as error:
                        raise SandboxError("Invalid compressed checkpoint archive") from error
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limits.max_bytes:
                        raise SandboxError("Checkpoint archive exceeds its limit")
                    expanded.write(chunk)
            expanded.flush()
            expanded.seek(0)
            yield expanded


def _preflight(stream: BinaryIO, limits: CheckpointLimits) -> None:
    """Bound extension headers before tarfile allocates their payloads.

    Also requires the stream to reach its end-of-archive marker.
    """
    length = os.fstat(stream.fileno()).st_size
    offset, headers, extensions = 0, 0, 0
    while offset + 512 <= length:
        stream.seek(offset)
        header = stream.read(512)
        if header == b"\x00" * 512:
            stream.seek(0)
            return
        try:
            info = tarfile.TarInfo.frombuf(header, encoding="utf-8", errors="surrogateescape")
        except tarfile.TarError as error:
            raise SandboxError("Invalid checkpoint archive framing") from error
        headers += 1
        if info.size < 0 or offset + 512 + info.size > length or headers > limits.max_entries * 3:
            raise SandboxError("Invalid checkpoint archive framing")
        if info.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
            extensions += info.size
            if info.size > limits.max_manifest_bytes or extensions > limits.max_manifest_bytes * 16:
                raise SandboxError("Checkpoint extension metadata exceeds its limit")
        offset += 512 + ((info.size + 511) // 512) * 512
    # Running out of bytes instead of reaching the end-of-archive marker means the stream
    # stopped early. A cut on a member boundary otherwise reads as a whole archive that
    # happens to hold fewer files, and its digest matches those bytes.
    raise SandboxError("Checkpoint archive ends without its end-of-archive marker")


def _discard(path: Path) -> None:
    """Remove a partial restore tree without masking the failure that caused it.

    A restored directory can be read-only, which stops its children being unlinked,
    so modes are reopened top down and each directory is writable before it is
    entered. Nothing here may raise: this runs while another exception is in flight.
    """
    for parent, directories, _ in os.walk(path):
        for directory in directories:
            child = os.path.join(parent, directory)
            # A symlink to a directory is listed here and chmod would follow it, so an
            # archive's link could retarget this outside the tree. Links need no mode:
            # removal unlinks them, and the walk does not descend through them.
            if not os.path.islink(child):
                with suppress(OSError):
                    os.chmod(child, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except (NotImplementedError, OSError) as error:
        if isinstance(error, OSError) and error.errno not in (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise
        raise SandboxError("Checkpoint storage requires directory fsync; use a filesystem that supports it") from error


class CheckpointArchive:
    """Tar with exactly workspace/native roots and a JSON state manifest.

    ``compress`` selects the representation this instance writes; reading accepts
    either one, so an archive written before compression existed still restores.
    Native credentials must live outside the declared native root. Explicit
    exclusions are relative to either root, for example ``native/auth.json``.
    User workspace files, including ignored/untracked files, are otherwise kept.
    Restore rejects special files, hardlinks, escaping symlinks and duplicate paths.

    A symlink to an absolute path, such as a virtualenv's interpreter link, is kept
    verbatim: it names the computer's filesystem, not the one of whoever restores it, so
    only a restore inside the computer recreates it.
    """

    def __init__(self, limits: CheckpointLimits = CheckpointLimits(), *, compress: bool = True) -> None:
        self.limits = limits
        self.compress = compress

    def capture(
        self, roots: Mapping[str, Path], destination: Path, *, state: Mapping[str, Any], exclude: Sequence[str] = ()
    ) -> None:
        if set(roots) != _ROOTS:
            raise ValueError("Checkpoint requires workspace and native roots")
        exclusions = set(exclude)
        for item in exclusions:
            if str(_name(item)) == _MANIFEST or item in _ROOTS:
                raise ValueError("Cannot exclude a manifest or entire durable root")
        manifest = json.dumps(
            {"version": 1, "state": dict(state), "excluded": sorted(exclusions)}, allow_nan=False
        ).encode()
        if len(manifest) > self.limits.max_manifest_bytes:
            raise SandboxError("Checkpoint manifest exceeds its limit")
        count, size = 1, len(manifest)
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        root_paths = {name: Path(path).resolve() for name, path in roots.items()}
        for name, original in roots.items():
            if Path(original).is_symlink() or not root_paths[name].is_dir():
                raise SandboxError("Durable roots must be real directories")
            if destination.resolve().is_relative_to(root_paths[name]):
                raise SandboxError("Checkpoint destination cannot be inside a captured root")
        # An exclusion names one archive prefix, so a root that contains the other would
        # carry an excluded file in under that other prefix. Compared resolved: neither
        # root has to be a link for an ancestor of one to be an alias of the other.
        if root_paths["workspace"].is_relative_to(root_paths["native"]) or root_paths["native"].is_relative_to(
            root_paths["workspace"]
        ):
            raise SandboxError("Durable roots must not overlap")
        # An exclusion names a path, but a hardlink is a second name for the same bytes.
        # Collect the inodes behind each exclusion so an alias cannot smuggle them in.
        # Only possible while the excluded path exists: once its original is unlinked, a
        # surviving link is indistinguishable from a file that was never excluded.
        excluded_inodes: Dict[Tuple[int, int], str] = {}
        links: Dict[str, tarfile.TarInfo] = {}

        def collect(path: Path, name: str) -> None:
            entry = path.lstat()
            if stat.S_ISDIR(entry.st_mode):
                for child in sorted(path.iterdir()):
                    collect(child, name + "/" + child.name)
            elif stat.S_ISREG(entry.st_mode) and entry.st_nlink > 1:
                excluded_inodes.setdefault((entry.st_dev, entry.st_ino), name)

        for item in sorted(exclusions):
            parts = PurePosixPath(item).parts
            root = root_paths[parts[0]]
            excluded = root.joinpath(*parts[1:])
            # Resolve before walking. A symlinked component would otherwise send this
            # outside the root and enumerate a tree the roots do not contain, and such a
            # path excludes nothing inside the root anyway.
            if os.path.lexists(excluded) and _resolved(excluded).is_relative_to(root):
                collect(excluded, item)
        output_file = destination.open("xb")
        try:
            # Closing order: the tar's end-of-archive marker is written first, then the
            # encoder flushes, then the file closes.
            with (
                output_file as output,
                _encoder(output, self.compress) as sink,
                tarfile.open(fileobj=sink, mode="w", format=tarfile.PAX_FORMAT) as archive,
            ):
                info = tarfile.TarInfo(_MANIFEST)
                info.size = len(manifest)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(manifest))

                def add(path: Path, name: str) -> None:
                    nonlocal count, size
                    if any(name == item or name.startswith(item + "/") for item in exclusions):
                        return
                    _name(name)
                    count += 1
                    if count > self.limits.max_entries:
                        raise CheckpointContentError("Checkpoint has too many entries")
                    entry = path.lstat()
                    info = tarfile.TarInfo(name)
                    info.mode = entry.st_mode & 0o777
                    info.mtime = entry.st_mtime
                    if stat.S_ISREG(entry.st_mode):
                        info.type, info.size = tarfile.REGTYPE, entry.st_size
                    elif stat.S_ISDIR(entry.st_mode):
                        info.type = tarfile.DIRTYPE
                    elif stat.S_ISLNK(entry.st_mode):
                        info.type, info.linkname = tarfile.SYMTYPE, os.readlink(path)
                    else:
                        raise CheckpointContentError(
                            f"Checkpoint contains an unsupported file type at {name!r}; exclude it before capture"
                        )
                    if info.isdir():
                        archive.addfile(info)
                        for child in sorted(path.iterdir()):
                            add(child, name + "/" + child.name)
                    elif info.issym():
                        _link(name, info.linkname)
                        # Checked against the captured graph once every link is known, never
                        # by resolving here: an absolute target would be read on this host.
                        links[name] = info
                        archive.addfile(info)
                    elif info.isfile():
                        alias = excluded_inodes.get((entry.st_dev, entry.st_ino))
                        if alias is not None:
                            raise CheckpointContentError(
                                f"Checkpoint entry {name!r} is a hardlink to excluded {alias!r}"
                            )
                        size += info.size
                        if size > self.limits.max_bytes:
                            raise CheckpointContentError("Checkpoint data exceeds its limit")
                        with _regular(path) as source:
                            before = os.fstat(source.fileno())
                            if (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns) != (
                                entry.st_ino,
                                entry.st_dev,
                                entry.st_size,
                                entry.st_mtime_ns,
                            ):
                                raise SandboxError("Workspace changed during checkpoint capture")
                            archive.addfile(info, source)
                            after = os.fstat(source.fileno())
                            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                                after.st_size,
                                after.st_mtime_ns,
                                after.st_ino,
                            ) or before.st_size != info.size:
                                raise SandboxError("Workspace changed during checkpoint capture")
                    else:
                        raise SandboxError("Checkpoint contains an unsupported file type")
                    if sink.tell() > self.limits.max_bytes:
                        raise CheckpointContentError("Checkpoint archive exceeds its limit")

                for name in sorted(_ROOTS):
                    add(root_paths[name], name)
                _validate_link_graph(links)
                # Closed here, not by the block, because only an open encoder reports the
                # expanded length and the end-of-archive marker has to be in it first.
                archive.close()
                if sink.tell() > self.limits.max_bytes:
                    raise CheckpointContentError("Checkpoint archive exceeds its limit")
            # Restore bounds the stored bytes too, and compression is not guaranteed to
            # shrink what it wraps.
            if destination.stat().st_size > self.limits.max_bytes:
                raise CheckpointContentError("Checkpoint archive exceeds its limit")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    async def acapture(
        self, roots: Mapping[str, Path], destination: Path, *, state: Mapping[str, Any], exclude: Sequence[str] = ()
    ) -> None:
        await _thread(self.capture, roots, destination, state=state, exclude=exclude)

    def _inspect(self, archive: tarfile.TarFile) -> tuple[Dict[str, Any], Dict[str, tarfile.TarInfo]]:
        members: Dict[str, tarfile.TarInfo] = {}
        total = 0
        for member in archive:
            _name(member.name)
            if member.name in members:
                raise SandboxError("Duplicate checkpoint path")
            if not (member.isdir() or member.isfile() or member.issym()) or member.sparse is not None:
                raise CheckpointContentError(
                    f"Checkpoint contains an unsupported file type at {member.name!r}; exclude it before capture"
                )
            if member.size < 0 or (not member.isfile() and member.size != 0):
                raise SandboxError("Invalid checkpoint member size")
            if member.issym():
                _link(member.name, member.linkname)
            total += member.size
            members[member.name] = member
            if total > self.limits.max_bytes or len(members) > self.limits.max_entries:
                raise CheckpointContentError("Checkpoint exceeds restore limits")
        if any(root not in members or not members[root].isdir() for root in _ROOTS):
            raise SandboxError("Checkpoint is missing durable roots")
        for name in members:
            for parent in PurePosixPath(name).parents:
                if str(parent) != "." and (str(parent) not in members or not members[str(parent)].isdir()):
                    raise SandboxError("Checkpoint parent is not a declared directory")
        manifest_info = members.get(_MANIFEST)
        if manifest_info is None or not manifest_info.isfile() or manifest_info.size > self.limits.max_manifest_bytes:
            raise SandboxError("Invalid checkpoint manifest")
        manifest_file = archive.extractfile(manifest_info)
        assert manifest_file is not None
        try:
            manifest = json.load(manifest_file)
        except (ValueError, RecursionError) as error:
            raise SandboxError("Invalid checkpoint manifest") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("version") != 1
            or not isinstance(manifest.get("state"), dict)
        ):
            raise SandboxError("Unsupported checkpoint manifest")
        _validate_link_graph(members)
        return manifest, members

    def validate(self, source: Path) -> Dict[str, Any]:
        """Validate archive framing, roots, metadata and the complete link graph without extracting."""
        with _archive_bytes(Path(source), self.limits) as stream:
            _preflight(stream, self.limits)
            with tarfile.open(fileobj=stream, mode="r:") as archive:
                manifest, _ = self._inspect(archive)
                return manifest["state"]

    async def avalidate(self, source: Path) -> Dict[str, Any]:
        return await _thread(self.validate, source)

    def restore(self, source: Path, destination: Path, *, absolute_links: bool = False) -> Dict[str, Any]:
        """Restore into a new directory; failure never exposes a partial destination.

        ``destination`` then holds the archive's two roots: ``workspace/``, the agent's
        working directory as the turn left it, with the pinned checkout under
        ``workspace/repository`` when the agent has a repository configured, and
        ``native/``, the harness home with its conversation transcript and local history
        database, less the credential files excluded at capture. The manifest is not
        written out; its state is the return value.

        Symlinks to absolute paths are left out unless ``absolute_links`` is set, so
        nothing restored on a host can lead to that host's own files. Set it only inside
        the computer the restored roots belong to, where those paths are the ones the
        captured links named.

        The parent directory is trusted coordinator-owned storage. It must not be
        writable by sandbox processes or concurrent callers targeting this path.
        """
        source, destination = Path(source), Path(destination)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        # Resolved once: the symlink check below resolves each materialized link, so a
        # symlink anywhere in the parent's own path would otherwise fail every comparison.
        temporary = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination.parent)).resolve()
        try:
            with _archive_bytes(source, self.limits) as stream:
                _preflight(stream, self.limits)
                with tarfile.open(fileobj=stream, mode="r:") as archive:
                    manifest, members = self._inspect(archive)
                    # No extractall: validate the entire member graph before creating paths.
                    for name, member in sorted(
                        members.items(), key=lambda item: (len(PurePosixPath(item[0]).parts), item[0])
                    ):
                        if name == _MANIFEST:
                            continue
                        path = temporary / name
                        if member.isdir():
                            path.mkdir(mode=0o700)
                        elif member.issym():
                            if not member.linkname.startswith("/"):
                                path.symlink_to(member.linkname)
                        else:
                            extracted = archive.extractfile(member)
                            assert extracted is not None
                            with path.open("xb") as output:
                                shutil.copyfileobj(extracted, output, _CHUNK)
                            path.chmod(member.mode & 0o777)
                    for name, member in members.items():
                        if member.issym() and not member.linkname.startswith("/"):
                            root = temporary / PurePosixPath(name).parts[0]
                            if not _resolved(temporary / name).is_relative_to(root):
                                raise CheckpointContentError("Checkpoint symlink chain escapes its durable root")
                    # After the check, which would otherwise resolve them against this filesystem.
                    for name, member in members.items():
                        if absolute_links and member.issym() and member.linkname.startswith("/"):
                            (temporary / name).symlink_to(member.linkname)
                    # Last pass, deepest first: materializing a child retimes its parent,
                    # and a directory stays writable until its own children exist.
                    for name, member in sorted(members.items(), reverse=True):
                        path = temporary / name
                        if name == _MANIFEST or not os.path.lexists(path):
                            continue
                        times = (member.mtime, member.mtime)
                        try:
                            if member.issym():
                                # Stamp the link itself; following it would retime its target.
                                os.utime(path, times, follow_symlinks=False)
                            else:
                                os.utime(path, times)
                        except (OverflowError, ValueError) as error:
                            # A hostile archive can carry a NaN or out-of-range timestamp.
                            raise SandboxError("Invalid checkpoint timestamp") from error
                        if member.isdir():
                            path.chmod(member.mode & 0o777)
            os.rename(temporary, destination)
            return manifest["state"]
        except tarfile.TarError as error:
            # Scoped by type, not by block: only the tarfile calls above can raise it,
            # namely opening the archive, walking members and reading a member's bytes.
            raise SandboxError("Invalid checkpoint archive") from error
        finally:
            _discard(temporary)

    async def arestore(self, source: Path, destination: Path, *, absolute_links: bool = False) -> Dict[str, Any]:
        return await _thread(self.restore, source, destination, absolute_links=absolute_links)


@runtime_checkable
class CheckpointStore(Protocol):
    """Immutable checkpoint objects addressed by the digest of their stored bytes.

    An implementation owns where those bytes live and nothing more: capture,
    validation and restore all belong to ``CheckpointArchive``. A reference is only
    publishable after the durable run commit, and ``delete`` belongs to retention
    rather than to compute destruction, so destroying compute never removes an object.

    Reading an object that is absent raises ``CheckpointObjectNotFound``; one that is
    oversized, or that does not match its reference, raises ``SandboxError``. ``delete``
    is the exception, because removing an object that is already gone succeeds. Every
    other filesystem or transport failure is passed through unchanged, except that
    an unavailable required filesystem primitive raises ``SandboxError`` with its
    original failure as the cause when available.
    """

    def put(self, source: Path) -> CheckpointRef:
        """Store ``source`` and return the reference describing its stored bytes."""
        ...

    async def aput(self, source: Path) -> CheckpointRef: ...

    def verify(self, reference: CheckpointRef) -> None:
        """Check the stored object and raise unless its size and digest both match.

        A store may answer from what it recorded at ``put`` rather than re-reading the
        bytes; ``open_archive`` always checks the bytes it hands out. Raises
        ``CheckpointObjectNotFound`` when storage no longer holds it. Reading one back is
        ``open_archive``'s job: an object need not have a path.
        """
        ...

    async def averify(self, reference: CheckpointRef) -> None: ...

    def open_archive(self, reference: CheckpointRef) -> ContextManager[Path]:
        """Verify the object, then yield a path holding its stored archive bytes.

        The bytes are the ones the reference names, not a decoded archive, so the
        digest still describes what the caller reads.

        The store owns the path and it is valid only inside the context. Exiting
        releases whatever the store materialized to produce it, on an exception as much
        as on success, and never removes the object itself. Concurrent and repeated
        accesses are independent.
        """
        ...

    def aopen_archive(self, reference: CheckpointRef) -> AsyncContextManager[Path]:
        """Async ``open_archive``, with the same ownership and lifetime, and releasing
        what it materialized under cancellation too."""
        ...

    def delete(self, reference: CheckpointRef) -> None:
        """Remove the object. Removing one that is already gone is not an error."""
        ...

    async def adelete(self, reference: CheckpointRef) -> None: ...


class FileCheckpointStore:
    """Content-addressed immutable objects on trusted shared durable storage.

    A service-host local disk does not cover host loss. Production callers must
    choose storage whose replication/durability matches their recovery promise.
    Objects are unreachable until a database transaction publishes their reference.
    Deletion/retention is intentionally separate from compute destruction. Objects are
    stored read-only, so a path leased by ``open_archive`` cannot alter them.
    """

    def __init__(self, root: Path, *, max_bytes: int = 1024 * 1024 * 1024) -> None:
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("Checkpoint store root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Checkpoint object limit must be positive")
        self.max_bytes = max_bytes

    def put(self, source: Path) -> CheckpointRef:
        fd, name = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        temporary = Path(name)
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as output, _regular(Path(source)) as stream:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise SandboxError("Checkpoint object exceeds its limit")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
                # Every name for this object, including the ones open_archive leases out, shares
                # its mode, so the bytes a reference describes cannot be edited through any of them.
                os.fchmod(output.fileno(), 0o400)
            reference = CheckpointRef(digest.hexdigest(), size)
            target = self.root / reference.sha256
            try:
                os.link(temporary, target)
            except FileExistsError:
                self.verify(reference)
            except (NotImplementedError, OSError) as error:
                if isinstance(error, OSError) and error.errno not in (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
                    raise
                raise SandboxError("Checkpoint storage requires filesystem hard links for publication") from error
            _fsync_directory(self.root)
            return reference
        finally:
            temporary.unlink(missing_ok=True)

    async def aput(self, source: Path) -> CheckpointRef:
        return await _thread(self.put, source)

    def verify(self, reference: CheckpointRef) -> None:
        self._verify(self.root / reference.sha256, reference)

    def _verify(self, path: Path, reference: CheckpointRef) -> None:
        if reference.size > self.max_bytes:
            raise SandboxError("Checkpoint object exceeds its limit")
        digest, size = hashlib.sha256(), 0
        try:
            stream = _regular(path)
        except FileNotFoundError as error:
            raise CheckpointObjectNotFound("Checkpoint object is missing") from error
        with stream:
            if os.fstat(stream.fileno()).st_size != reference.size:
                raise SandboxError("Checkpoint size mismatch")
            while chunk := stream.read(_CHUNK):
                size += len(chunk)
                if size > reference.size:
                    raise SandboxError("Checkpoint object changed while reading")
                digest.update(chunk)
        if size != reference.size or digest.hexdigest() != reference.sha256:
            raise SandboxError("Checkpoint checksum mismatch")

    async def averify(self, reference: CheckpointRef) -> None:
        await _thread(self.verify, reference)

    @contextmanager
    def _lease(self, reference: CheckpointRef) -> Iterator[Path]:
        """Hold the object's bytes under a private name for as long as the lease lasts.

        Retention unlinks the canonical name on its own schedule, which a reader that
        already holds the object must not see disappear. A second link keeps those exact
        bytes reachable; releasing it leaves the object itself alone.
        """
        lease = self.root / f".open-{os.urandom(8).hex()}"
        try:
            os.link(self.root / reference.sha256, lease)
        except FileNotFoundError as error:
            raise CheckpointObjectNotFound("Checkpoint object is missing") from error
        except (NotImplementedError, OSError) as error:
            if isinstance(error, OSError) and error.errno not in (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise
            raise SandboxError("Checkpoint storage requires filesystem hard links for archive leases") from error
        try:
            yield lease
        finally:
            lease.unlink(missing_ok=True)

    @contextmanager
    def open_archive(self, reference: CheckpointRef) -> Iterator[Path]:
        """Lease the object, verify the leased file, and yield it.

        The file handed out is the file that was checked, and retention removing the
        canonical name after the lease exists cannot fail the check.
        """
        with self._lease(reference) as lease:
            self._verify(lease, reference)
            yield lease

    @asynccontextmanager
    async def aopen_archive(self, reference: CheckpointRef) -> AsyncIterator[Path]:
        with self._lease(reference) as lease:
            # _thread drains the verification before a cancellation propagates, so the
            # lease is released only once nothing is still reading it.
            await _thread(self._verify, lease, reference)
            yield lease

    def delete(self, reference: CheckpointRef) -> None:
        # Durable, because a reconciler that crashes must not find the object again.
        (self.root / reference.sha256).unlink(missing_ok=True)
        _fsync_directory(self.root)

    async def adelete(self, reference: CheckpointRef) -> None:
        await _thread(self.delete, reference)

    def restore(
        self, reference: CheckpointRef, destination: Path, *, archive: CheckpointArchive | None = None
    ) -> Dict[str, Any]:
        # The store is coordinator-owned and immutable. Sandboxes never mount it.
        # One access, one verification: the access already established integrity.
        with self.open_archive(reference) as source:
            return (archive or CheckpointArchive()).restore(source, destination)

    async def arestore(
        self, reference: CheckpointRef, destination: Path, *, archive: CheckpointArchive | None = None
    ) -> Dict[str, Any]:
        return await _thread(self.restore, reference, destination, archive=archive)
