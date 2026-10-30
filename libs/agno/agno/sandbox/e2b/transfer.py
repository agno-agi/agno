"""Checkpoint transport for E2B computers, through the E2B file and command APIs."""

import asyncio
import json
import shlex
import tarfile
import tempfile
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from agno.sandbox.base import SandboxError, SandboxHandle, _sync
from agno.sandbox.checkpoint import (
    _MANIFEST,
    _ROOTS,
    CheckpointArchive,
    CheckpointRef,
    CheckpointStore,
    _archive_bytes,
    _name,
)
from agno.sandbox.e2b._archive import _TRANSFER_DIR
from agno.sandbox.e2b.sandbox import E2BSandbox
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS

# Export and import may take this long inside the computer.
_JOB_TIMEOUT = 900


class E2BCheckpointTransfer:
    """Move checkpoints in and out of E2B computers.

    Implements the ``CheckpointTransfer`` protocol. Inside the computer, root
    stops the agent user's processes and a child dropped to that user runs the
    shared ``CheckpointArchive``, writing into a root-only directory. The archive
    streams through the E2B file API and the host validates it before storing or
    sending it. Restore fills an empty, unused generation; a failed restore kills
    the computer. ``scratch`` holds unencrypted archives in transit and must be
    coordinator-private.
    """

    def __init__(
        self,
        provider: E2BSandbox,
        store: CheckpointStore,
        *,
        archive: Optional[CheckpointArchive] = None,
        scratch: Optional[Path] = None,
    ) -> None:
        self.provider, self.store, self.scratch = provider, store, scratch
        self.archive = archive or CheckpointArchive()

    async def _job(self, connection: Any, operation: str, path: str, job: Mapping[str, Any]) -> Any:
        from e2b import CommandExitException

        command = shlex.join(
            ["python", "-I", "-m", "agno.sandbox.e2b._archive", operation, path, json.dumps(dict(job))]
        )
        try:
            reply = await connection.commands.run(command, user="root", cwd="/", timeout=_JOB_TIMEOUT)
        except CommandExitException as error:
            raise SandboxError(f"Checkpoint {operation} failed: " + (error.stderr or error.stdout)[-1500:]) from None
        except Exception as error:
            raise SandboxError(f"Checkpoint {operation} failed: {str(error)[:500] or type(error).__name__}") from error
        try:
            return json.loads(reply.stdout)
        except ValueError as error:
            raise SandboxError(f"Checkpoint {operation} returned an invalid reply") from error

    async def _download_connection(self, handle: SandboxHandle) -> Any:
        """An HTTP/1.1 connection for reading archives out of a computer the provider checked.

        E2B sends file contents in small HTTP/2 DATA frames, and the SDK's HTTP/2 client drops the
        connection as abusive after a few megabytes; HTTP/1.1 has no frames to count.
        """
        from e2b import AsyncSandbox

        return await AsyncSandbox.connect(handle.provider_ref, http_version="1.1", **self.provider._options)

    async def _pull(self, connection: Any, path: str, size: int, destination: Path) -> None:
        if size > self.archive.limits.max_bytes:
            raise SandboxError("Checkpoint export exceeds the archive byte limit")
        received = 0
        with destination.open("xb") as output:
            stream = await connection.files.read(path, format="stream", user="root", request_timeout=_JOB_TIMEOUT)
            async for chunk in stream:
                received += len(chunk)
                if received > size:
                    raise SandboxError("Checkpoint export is larger than its reported size")
                await asyncio.to_thread(output.write, chunk)
        if received != size:
            raise SandboxError("Checkpoint export changed size while it was read")

    def _check_excluded(self, path: Path, exclude: Sequence[str]) -> None:
        exclusions = set(exclude)
        with _archive_bytes(path, self.archive.limits) as stream:
            with tarfile.open(fileobj=stream, mode="r:") as archive:
                for member in archive:
                    if member.name == _MANIFEST:
                        manifest = json.loads(archive.extractfile(member).read())  # type: ignore[union-attr]
                        if set(manifest.get("excluded", [])) != exclusions:
                            raise SandboxError("Checkpoint export does not record the requested exclusions")
                    elif any(member.name == item or member.name.startswith(item + "/") for item in exclusions):
                        raise SandboxError(f"Checkpoint export contains excluded path {member.name!r}")
                # Validation stops at the end marker, but the store uploads the whole
                # file, so anything after it would reach storage unchecked.
                stream.seek(archive.offset)
                while chunk := stream.read(1024 * 1024):
                    if chunk.count(0) != len(chunk):
                        raise SandboxError("Checkpoint export has data after the end of the archive")

    @staticmethod
    def _check_exclusions(exclude: Sequence[str]) -> None:
        # The rules capture applies inside the computer, checked before anything is stopped.
        for item in exclude:
            if str(_name(item)) == _MANIFEST or item in _ROOTS:
                raise ValueError("Cannot exclude a manifest or entire durable root")

    async def _remove(self, connection: Any, path: str) -> None:
        with suppress(Exception):
            await connection.files.remove(path, user="root")

    async def acapture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef:
        self._check_exclusions(exclude)
        connection = await self.provider._connection(handle)
        remote = f"{_TRANSFER_DIR}/{uuid4().hex}.tar"
        try:
            exported = await self._job(
                connection,
                "capture",
                remote,
                {"state": dict(state), "exclude": list(exclude), "limits": asdict(self.archive.limits)},
            )
            with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.scratch) as directory:
                path = Path(directory) / "checkpoint.tar"
                download = await self._download_connection(handle)
                await self._pull(download, remote, int(exported["size"]), path)
                # The archive was written by the agent's user, so check its structure and the exclusions here.
                await self.archive.avalidate(path)
                await asyncio.to_thread(self._check_excluded, path, exclude)
                return await self.store.aput(path)
        finally:
            # Cleanup must never turn a stored checkpoint into an error.
            await asyncio.shield(self._remove(connection, remote))

    def capture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef:
        return _sync(self.acapture(handle, state=state, exclude=exclude))

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        remote = f"{_TRANSFER_DIR}/{uuid4().hex}.tar"
        # The computer is left alone until bytes reach it, so a missing or invalid checkpoint never kills it.
        sent = False
        try:
            async with self.store.aopen_archive(reference) as checkpoint:
                state = await self.archive.avalidate(checkpoint)
                connection = await self.provider._connection(handle)
                sent = True
                with checkpoint.open("rb") as stream:
                    await connection.files.write(remote, stream, user="root", request_timeout=_JOB_TIMEOUT)
            reply = await self._job(connection, "restore", remote, {"limits": asdict(self.archive.limits)})
            if reply["state"] != state:
                raise SandboxError("Restored manifest differs from the verified checkpoint")
            return state
        except BaseException:
            # A partially restored computer must never execute another turn.
            if sent:
                await asyncio.shield(self.provider.astop(handle))
            raise

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        return _sync(self.arestore(handle, reference))
