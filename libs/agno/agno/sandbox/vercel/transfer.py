"""Checkpoint transport for Vercel computers, through the guest guard and the SDK's file API."""

import asyncio
import json
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
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS
from agno.sandbox.vercel.guard import EXPORT, MAX_ARCHIVE
from agno.sandbox.vercel.sandbox import VercelSandbox, _NotSent
from agno.utils.log import log_warning

# Codex rebuilds its plugin clone and commit marker; neither contains conversation state.
VERCEL_NATIVE_EXCLUSIONS = (*DEFAULT_NATIVE_EXCLUSIONS, "native/codex/.tmp/plugins", "native/codex/.tmp/plugins.sha")

# Bounds the guard's own timers: it archives in a child that gets 30 minutes.
_CAPTURE_SECONDS = 2100.0
_RESTORE_SECONDS = 1800.0
_REMOVE_SECONDS = 60.0


class VercelCheckpointTransfer:
    """Move checkpoints in and out of Vercel computers.

    Implements the ``CheckpointTransfer`` protocol. Inside the computer a child dropped to the agent
    user runs the shared ``CheckpointArchive`` while the agent's processes are stopped, so root never
    reads paths the agent controls. The host validates every archive before it is stored or sent. Restore
    fills an unused computer; if one fails after the request was sent, the computer is stopped, because
    it must never run another turn. ``scratch`` holds unencrypted archives in transit and must be
    private to the coordinator.
    """

    def __init__(
        self,
        provider: VercelSandbox,
        store: CheckpointStore,
        *,
        archive: Optional[CheckpointArchive] = None,
        scratch: Optional[Path] = None,
    ) -> None:
        self.provider, self.store, self.scratch = provider, store, scratch
        self.archive = archive or CheckpointArchive()
        if self.archive.limits.max_bytes > MAX_ARCHIVE:
            raise ValueError("Vercel checkpoints are limited to 2 GiB")

    @staticmethod
    def _check_exclusions(exclude: Sequence[str]) -> None:
        # The rules capture applies inside the computer, checked before the agent is stopped.
        for item in exclude:
            if str(_name(item)) == _MANIFEST or item in _ROOTS:
                raise ValueError("Cannot exclude a manifest or entire durable root")

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
                # The store keeps all bytes, including any payload after the archive end marker.
                stream.seek(archive.offset)
                while chunk := stream.read(1024 * 1024):
                    if chunk.count(0) != len(chunk):
                        raise SandboxError("Checkpoint export has data after the end of the archive")

    async def _download(self, handle: SandboxHandle, name: str, size: int, destination: Path) -> None:
        if size < 1 or size > self.archive.limits.max_bytes:
            raise SandboxError("Checkpoint export exceeds the archive byte limit")
        await self.provider._read_file(handle, f"{EXPORT}/{name}.tar", size, destination)

    async def acapture(
        self,
        handle: SandboxHandle,
        *,
        state: Mapping[str, Any],
        exclude: Sequence[str] = VERCEL_NATIVE_EXCLUSIONS,
    ) -> CheckpointRef:
        self._check_exclusions(exclude)
        name = uuid4().hex
        request = {"state": dict(state), "exclude": list(exclude), "limits": asdict(self.archive.limits)}
        try:
            reply = await self.provider._guard_call(handle, "capture", name, request=request, timeout=_CAPTURE_SECONDS)
            with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.scratch) as directory:
                path = Path(directory) / "checkpoint.tar"
                await self._download(handle, name, int(reply["size"]), path)
                # Written inside the computer, where the agent can reach it: check its structure and exclusions here.
                await self.archive.avalidate(path)
                await asyncio.to_thread(self._check_excluded, path, exclude)
                return await self.store.aput(path)
        finally:
            # Export cleanup must not fail a stored checkpoint; interrupted capture recovers on the next operation.
            with suppress(Exception):
                await asyncio.shield(self.provider._guard_call(handle, "remove", name, timeout=_REMOVE_SECONDS))

    def capture(
        self,
        handle: SandboxHandle,
        *,
        state: Mapping[str, Any],
        exclude: Sequence[str] = VERCEL_NATIVE_EXCLUSIONS,
    ) -> CheckpointRef:
        return _sync(self.acapture(handle, state=state, exclude=exclude))

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        name = uuid4().hex
        # Validate locally before a restore failure can require stopping the computer.
        sent = False
        try:
            async with self.store.aopen_archive(reference) as checkpoint:
                state = await self.archive.avalidate(checkpoint)
                sent = True
                reply = await self.provider._guard_call(
                    handle,
                    "restore",
                    name,
                    request={"limits": asdict(self.archive.limits)},
                    archive=checkpoint,
                    timeout=_RESTORE_SECONDS,
                )
            if reply.get("state") != state:
                raise SandboxError("Restored manifest differs from the verified checkpoint")
            return state
        except BaseException as error:
            # Stop a possibly partial restore, but leave untouched or replaced sessions alone.
            if sent and not isinstance(error, _NotSent):
                failure = await self.provider._stop_quietly(handle)
                if failure is not None:
                    log_warning(f"Could not stop the Vercel computer after a failed restore: {failure}")
            raise

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        return _sync(self.arestore(handle, reference))
