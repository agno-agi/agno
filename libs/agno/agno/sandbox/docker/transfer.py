"""Checkpoint transport for Docker-managed bounded session volumes."""

import asyncio
import copy
import io
import json
import tarfile
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from agno.sandbox.base import SandboxError, SandboxHandle, _sync
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointContentError,
    CheckpointRef,
    CheckpointStore,
    _archive_bytes,
    _drain,
    _encoder,
    _name,
    _preflight,
    _thread,
)
from agno.sandbox.docker.sandbox import DockerSandbox
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS


class DockerCheckpointTransfer:
    """Copy frozen filesystem state through the daemon without host bind mounts.

    The caller must own the session generation, drain the SDK and quiesce any
    application requiring a logical backup before capture. Pause freezes files,
    not application transactions. Restore targets a fresh, unused generation.
    ``scratch`` holds unencrypted archives in transit and must be coordinator-private;
    the system temporary directory is used when it is omitted.
    """

    def __init__(
        self,
        provider: DockerSandbox,
        store: CheckpointStore,
        *,
        archive: Optional[CheckpointArchive] = None,
        scratch: Optional[Path] = None,
    ) -> None:
        self.provider, self.store, self.scratch = provider, store, scratch
        self.archive = archive or CheckpointArchive()

    async def _copy(
        self,
        handle: SandboxHandle,
        source: str,
        destination: str,
        *,
        output: Optional[Path] = None,
        input_file: Optional[Path] = None,
        timeout: float = 120,
    ) -> None:
        # Never ask Docker to extract an untrusted archive on the control-plane
        # host. Capture writes raw bytes; restore sends a validated/repacked tar.
        # No --archive: on extract it chowns to the container's configured user, which the daemon
        # resolves as a name in its own passwd and so fails for "uid:gid"; the repacked tar pins ownership.
        stream = input_file.open("rb") if input_file is not None else None
        target = output.open("xb") if output is not None else None
        process = None
        tasks = []
        try:
            process = await asyncio.create_subprocess_exec(
                self.provider.docker_binary,
                "container",
                "cp",
                source,
                destination,
                stdin=stream if stream is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def stdout() -> None:
                size = 0
                assert process is not None and process.stdout is not None
                while chunk := await process.stdout.read(1024 * 1024):
                    size += len(chunk)
                    if target is not None and size > self.archive.limits.max_bytes:
                        raise CheckpointContentError("Checkpoint transfer exceeds its byte limit")
                    if target is None and size > 65536:
                        raise SandboxError("Checkpoint transfer exceeds its byte limit")
                    if target is not None:
                        await _thread(target.write, chunk)

            async def stderr() -> bytes:
                data = bytearray()
                assert process is not None and process.stderr is not None
                while chunk := await process.stderr.read(65536):
                    if len(data) + len(chunk) > 1024 * 1024:
                        raise SandboxError("Checkpoint transfer diagnostics exceeded their limit")
                    data.extend(chunk)
                return bytes(data)

            tasks = [asyncio.create_task(stdout()), asyncio.create_task(stderr())]
            values = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
            await asyncio.wait_for(process.wait(), 5)
            if process.returncode:
                error = values[1] or b""
                raise SandboxError("Docker checkpoint transfer failed: " + error.decode(errors="replace")[-1000:])
        except BaseException:
            if process is not None and process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            if stream is not None:
                stream.close()
            if target is not None:
                target.close()

    def _combine(
        self, exports: Mapping[str, Path], destination: Path, state: Mapping[str, Any], exclude: Sequence[str]
    ) -> None:
        exclusions = set(exclude)

        def excluded(name: str) -> bool:
            return any(name == value or name.startswith(value + "/") for value in exclusions)

        for value in exclusions:
            path = _name(value)
            if value == "manifest.json" or len(path.parts) == 1:
                raise ValueError("Cannot exclude an entire root or the manifest")
        manifest = json.dumps(
            {"version": 1, "state": dict(state), "excluded": sorted(exclusions)}, allow_nan=False
        ).encode()
        if len(manifest) > self.archive.limits.max_manifest_bytes:
            raise SandboxError("Checkpoint manifest exceeds its limit")
        with (
            destination.open("xb") as output,
            _encoder(output, self.archive.compress) as sink,
            tarfile.open(fileobj=sink, mode="w", format=tarfile.PAX_FORMAT) as target,
        ):
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mode = len(manifest), 0o600
            target.addfile(info, io.BytesIO(manifest))
            entries, total = 1, len(manifest)
            for root, source in sorted(exports.items()):
                with source.open("rb") as stream:
                    _preflight(stream, self.archive.limits)
                    with tarfile.open(fileobj=stream, mode="r:") as archive:
                        # Hardlinks share bytes, so an excluded alias would leak through a retained one.
                        seen = set()
                        for member in archive.getmembers():
                            if member.islnk():
                                if member.linkname not in seen:
                                    raise SandboxError("Docker export has a hardlink to a missing or later entry")
                                if excluded(member.name) != excluded(member.linkname):
                                    raise CheckpointContentError(
                                        "Excluded checkpoint path shares a hardlink with a retained path"
                                    )
                            seen.add(member.name)
                        for member in archive:
                            path = _name(member.name)
                            if path.parts[0] != root:
                                raise SandboxError("Docker export escaped its declared root")
                            if excluded(member.name):
                                continue
                            info = copy.copy(member)
                            info.pax_headers = {}
                            info.mode &= 0o777
                            info.uid = info.gid = 0
                            info.uname = info.gname = ""
                            if info.islnk():
                                if _name(info.linkname).parts[0] != root:
                                    raise SandboxError("Docker hardlink escaped its declared root")
                                linked = archive.getmember(info.linkname)
                                if not linked.isfile():
                                    raise SandboxError("Docker export has an unsupported hardlink chain")
                                info.type, info.size, info.linkname = tarfile.REGTYPE, linked.size, ""
                                info.mode = linked.mode & 0o777
                            entries += 1
                            total += info.size
                            if entries > self.archive.limits.max_entries or total > self.archive.limits.max_bytes:
                                raise CheckpointContentError("Checkpoint export exceeds its limits")
                            target.addfile(info, archive.extractfile(member) if info.isfile() else None)
                if target.offset > self.archive.limits.max_bytes:
                    raise CheckpointContentError("Checkpoint archive exceeds its limit")
        self.archive.validate(destination)

    async def _check_mounts(self, handle: SandboxHandle) -> None:
        if await self.provider._owned(handle) is None:
            raise SandboxError("Checkpoint computer is missing")
        code, out, _ = await self.provider._docker("container", "inspect", handle.provider_ref)
        if code:
            raise SandboxError("Could not inspect checkpoint mounts")
        mounts = {item["Destination"]: item for item in json.loads(out)[0].get("Mounts", [])}
        for role, destination in (("workspace", "/workspace"), ("runtime", "/runtime")):
            mount = mounts.get(destination, {})
            if (
                mount.get("Type") != "volume"
                or mount.get("Name") != handle.name + "-" + role
                or mount.get("RW") is not True
            ):
                raise SandboxError("Computer does not have checkpointable managed volumes")
            volume = await self.provider._volume(handle.name + "-" + role)
            expected = self.provider._volume_labels(
                handle.session_id, handle.agent_id, handle.generation, handle.config_digest, role
            )
            if volume is None or any((volume.get("Labels") or {}).get(key) != value for key, value in expected.items()):
                raise SandboxError("Checkpoint volume identity mismatch")
            options = volume.get("Options") or {}
            if volume.get("Driver") != "local" or options.get("type") != "tmpfs" or options.get("device") != "tmpfs":
                raise SandboxError("Unsupported checkpoint volume storage")

    async def _pause(self, handle: SandboxHandle) -> None:
        current = await self.provider._owned(handle)
        if current is None or current.state != "running":
            raise SandboxError("Checkpoint requires a running, exclusively owned computer")
        try:
            code, _, err = await self.provider._docker("container", "pause", handle.provider_ref)
        except BaseException:

            async def reconcile_pause() -> None:
                current = await self.provider._owned(handle)
                if current is not None and current.state == "paused":
                    await self._unpause(handle)

            await _drain(asyncio.create_task(reconcile_pause()))
            raise
        if code:
            raise SandboxError("Docker pause failed: " + err.decode(errors="replace")[-1000:])

    async def _unpause(self, handle: SandboxHandle) -> None:
        try:
            _, _, err = await self.provider._docker("container", "unpause", handle.provider_ref)
        except asyncio.TimeoutError:
            err = b"Unpause response timed out"
        current = await self.provider._owned(handle)
        if current is None or current.state != "running":
            raise SandboxError(
                "Could not confirm resumed compute after checkpoint: " + err.decode(errors="replace")[-1000:]
            )

    async def acapture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef:
        await self._check_mounts(handle)
        ready = await self.provider.aexec(handle, ["mkdir", "-p", "/runtime/native"])
        if ready.exit_code:
            raise SandboxError("Could not prepare the native state directory")
        with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.scratch) as directory:
            root = Path(directory)
            await self._pause(handle)
            cancelled = False
            try:
                await self._copy(handle, handle.provider_ref + ":/workspace", "-", output=root / "workspace.tar")
                await self._copy(handle, handle.provider_ref + ":/runtime/native", "-", output=root / "native.tar")
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                # Unpause always completes; once cancelled, cancellation stays the outcome even if it fails.
                task = asyncio.create_task(self._unpause(handle))
                if cancelled:
                    await _drain(task)
                else:
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        await _drain(task)
                        raise
            # Files no longer change after export. Validation and upload run outside
            # the pause, so storage latency does not freeze warm applications.
            await _thread(
                self._combine,
                {"workspace": root / "workspace.tar", "native": root / "native.tar"},
                root / "checkpoint.tar",
                state,
                exclude,
            )
            return await self.store.aput(root / "checkpoint.tar")

    def capture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef:
        return _sync(self.acapture(handle, state=state, exclude=exclude))

    def _split(self, checkpoint: Path, directory: Path) -> Tuple[Dict[str, Any], int]:
        """Validate a stored archive and write one import tar per root, expanding it once.

        Returns the manifest state and the captured native root mode.
        """
        limits = self.archive.limits
        modes = {}
        with _archive_bytes(checkpoint, limits) as stream:
            _preflight(stream, limits)
            with (
                tarfile.open(fileobj=stream, mode="r:") as source,
                tarfile.open(directory / "workspace.tar", "w", format=tarfile.PAX_FORMAT) as workspace,
                tarfile.open(directory / "native.tar", "w", format=tarfile.PAX_FORMAT) as native,
            ):
                manifest, members = self.archive._inspect(source)
                targets = {"workspace": workspace, "native": native}
                for name, member in members.items():
                    root, _, relative = name.partition("/")
                    if root not in targets:
                        continue
                    if not relative:
                        modes[root] = member.mode & 0o777
                        continue
                    info = copy.copy(member)
                    info.pax_headers = {}
                    info.name = relative
                    info.mode &= 0o777
                    info.uid = info.gid = 1000
                    info.uname = info.gname = ""
                    targets[root].addfile(info, source.extractfile(member) if member.isfile() else None)
        return manifest["state"], modes.get("native", 0o700)

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        await self._check_mounts(handle)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=self.scratch) as directory:
            root = Path(directory)
            async with self.store.aopen_archive(reference) as checkpoint:
                state, native_mode = await _thread(self._split, checkpoint, root)
            # The native directory is created here, so apply its captured mode rather than the umask.
            check = await self.provider.aexec(
                handle,
                [
                    "python",
                    "-I",
                    "-c",
                    "from pathlib import Path; w=Path('/workspace'); n=Path('/runtime/native'); assert not any(w.iterdir()), 'workspace is not empty'; n.mkdir(exist_ok=True); assert not any(n.iterdir()), 'native state is not empty'; n.chmod("
                    + oct(native_mode)
                    + ")",
                ],
            )
            if check.exit_code:
                raise SandboxError("Restore requires an empty, unused generation")
            await self._pause(handle)
            try:
                # This is the in-computer restore: docker cp extracts the tar as written, so
                # symlinks to absolute paths, such as a virtualenv's interpreter link, come back
                # verbatim. Moving this onto CheckpointArchive.restore would drop them unless it
                # passed absolute_links=True.
                await self._copy(handle, "-", handle.provider_ref + ":/workspace", input_file=root / "workspace.tar")
                await self._copy(handle, "-", handle.provider_ref + ":/runtime/native", input_file=root / "native.tar")
                await self._unpause(handle)
            except BaseException:
                # A partially restored computer must never execute another turn.
                # Unpause first: Docker stop cannot gracefully stop a paused one.
                with suppress(Exception):
                    await asyncio.shield(self._unpause(handle))
                await asyncio.shield(self.provider.astop(handle))
                raise
        return state

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        return _sync(self.arestore(handle, reference))
