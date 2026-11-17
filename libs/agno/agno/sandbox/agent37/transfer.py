"""Checkpoint transport for Agent 37 instances, through the exec API."""

import asyncio
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from agno.sandbox._roots import CONTENT_ERROR_EXIT
from agno.sandbox.agent37.sandbox import MAX_COMMAND_SECONDS, Agent37Sandbox
from agno.sandbox.base import SandboxError, SandboxHandle, _sync
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointContentError,
    CheckpointRef,
    CheckpointStore,
    check_excluded,
    check_exclusions,
)
from agno.sandbox.transfer import REMOTE_NATIVE_EXCLUSIONS


class Agent37CheckpointTransfer:
    """Move checkpoints in and out of Agent 37 instances through exec commands.

    Implements the ``CheckpointTransfer`` protocol. Inside the instance a process
    dropped to UID 1000 runs the shared ``CheckpointArchive`` while the agent's
    processes are stopped, and the host validates every archive that comes out.
    The exec API carries little per command, so an archive moves in chunks of 512 KiB
    in and 256 KiB out, a few at a time: large workspaces are slow. Restore fills an
    empty, unused generation, and this class stops an instance whose restore failed.
    ``scratch`` holds unencrypted archives in transit and must be coordinator-private.
    """

    def __init__(
        self,
        provider: Agent37Sandbox,
        store: CheckpointStore,
        *,
        archive: Optional[CheckpointArchive] = None,
        scratch: Optional[Path] = None,
    ) -> None:
        self.provider, self.store, self.scratch = provider, store, scratch
        self.archive = archive or CheckpointArchive()

    async def _running(self, handle: SandboxHandle) -> None:
        current = await self.provider._owned(handle)
        if current is None or current.state != "running":
            raise SandboxError("Checkpoint requires a running, exclusively owned computer")

    async def acapture(
        self,
        handle: SandboxHandle,
        *,
        state: Mapping[str, Any],
        exclude: Sequence[str] = REMOTE_NATIVE_EXCLUSIONS,
    ) -> CheckpointRef:
        check_exclusions(exclude)
        await self._running(handle)
        ref, name = handle.provider_ref, uuid4().hex
        job = json.dumps({"state": dict(state), "exclude": list(exclude), "limits": asdict(self.archive.limits)})
        staged, inline = await self.provider._input(ref, name, job.encode())
        try:
            reply = await self.provider._guest(ref, "capture", name, *staged, data=inline, timeout=MAX_COMMAND_SECONDS)
            failed = reply.get("failed")
            if isinstance(failed, dict):
                # Files that cannot be checkpointed fail the same way again, so the caller must not retry.
                kind = CheckpointContentError if failed.get("code") == CONTENT_ERROR_EXIT else SandboxError
                raise kind("Checkpoint capture failed: " + str(failed.get("error")).strip()[-1500:])
            with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.scratch) as directory:
                path = Path(directory) / "checkpoint.tar"
                with path.open("w+b") as output:
                    await self.provider._receive(ref, name, reply, output, self.archive.limits.max_bytes)
                # The archive was written inside the instance by a process of the agent's own user,
                # so check its structure and the exclusions here.
                await self.archive.avalidate(path)
                await asyncio.to_thread(check_excluded, path, self.archive.limits, exclude)
                return await self.store.aput(path)
        finally:
            # Cleanup must never turn a stored checkpoint into an error.
            await asyncio.shield(self.provider._discard(ref, name))

    def capture(
        self,
        handle: SandboxHandle,
        *,
        state: Mapping[str, Any],
        exclude: Sequence[str] = REMOTE_NATIVE_EXCLUSIONS,
    ) -> CheckpointRef:
        return _sync(self.acapture(handle, state=state, exclude=exclude))

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        ref, name = handle.provider_ref, uuid4().hex
        # The instance is left alone until a request reaches it, so a missing or invalid
        # checkpoint never stops it.
        sent = False
        try:
            async with self.store.aopen_archive(reference) as checkpoint:
                state = await self.archive.avalidate(checkpoint)
                await self._running(handle)
                sent = True
                with checkpoint.open("rb") as source:
                    staged = await self.provider._send(ref, name, source)
            limits = json.dumps(asdict(self.archive.limits))
            await self.provider._guest(ref, "restore", name, limits, *staged, timeout=MAX_COMMAND_SECONDS)
            return state
        except BaseException:
            # A partially restored computer must never execute another turn.
            if sent:
                await asyncio.shield(self.provider.astop(handle))
            raise

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        return _sync(self.arestore(handle, reference))
