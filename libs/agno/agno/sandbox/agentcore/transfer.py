"""Checkpoint transport for AgentCore microVMs, through runtime invocations."""

import asyncio
import base64
import tempfile
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from agno.sandbox.agentcore.sandbox import AgentCoreSandbox, _Refusal
from agno.sandbox.agentcore.server import _MAX_TRANSFER
from agno.sandbox.base import SandboxError, SandboxHandle, _sync
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointRef,
    CheckpointStore,
    check_excluded,
    check_exclusions,
)
from agno.sandbox.transfer import REMOTE_NATIVE_EXCLUSIONS

# Checkpoint bytes per invocation. Base64 makes the payload a third larger, well
# under AgentCore's 100 MB request and response limit.
_CHUNK = 8 * 1024 * 1024
AGENTCORE_NATIVE_EXCLUSIONS = REMOTE_NATIVE_EXCLUSIONS


class AgentCoreCheckpointTransfer:
    """Move checkpoints in and out of AgentCore microVMs through invocations.

    Implements the ``CheckpointTransfer`` protocol. Inside the microVM a process
    dropped to UID 1000 runs the shared ``CheckpointArchive`` while the agent's
    processes are stopped, so root never touches paths the agent controls. Archives
    move in chunks of at most 8 MiB and the host validates each one before storing
    or sending it. Restore fills a claimed, unused generation; the computer refuses
    all further work if a restore fails, and this class stops it.
    ``scratch`` holds unencrypted archives in transit and must be coordinator-private.
    """

    def __init__(
        self,
        provider: AgentCoreSandbox,
        store: CheckpointStore,
        *,
        archive: Optional[CheckpointArchive] = None,
        scratch: Optional[Path] = None,
    ) -> None:
        self.provider, self.store, self.scratch = provider, store, scratch
        self.archive = archive or CheckpointArchive()
        if self.archive.limits.max_bytes > _MAX_TRANSFER:
            raise ValueError("AgentCore checkpoints are limited to 2 GiB")

    async def _pull(self, handle: SandboxHandle, name: str, size: int, destination: Path) -> None:
        if size > self.archive.limits.max_bytes:
            raise SandboxError("Checkpoint export exceeds the archive byte limit")
        with destination.open("xb") as output:
            offset = 0
            while offset < size:
                reply = await self.provider._invoke_for(
                    handle, "get", name=name, offset=offset, length=min(_CHUNK, size - offset)
                )
                data = base64.b64decode(reply["data"], validate=True)
                if not data:
                    raise SandboxError("Checkpoint export ended before its reported size")
                await asyncio.to_thread(output.write, data)
                offset += len(data)
        if offset != size:
            raise SandboxError("Checkpoint export changed size while it was read")

    async def _push(self, handle: SandboxHandle, name: str, source: Path) -> None:
        with source.open("rb") as stream:
            offset = 0
            while True:
                data = await asyncio.to_thread(stream.read, _CHUNK)
                if not data:
                    return
                reply = await self.provider._invoke_for(
                    handle, "put", name=name, offset=offset, data=base64.b64encode(data).decode()
                )
                offset += len(data)
                if reply["size"] != offset:
                    raise SandboxError("Checkpoint import size mismatch")

    async def acapture(
        self,
        handle: SandboxHandle,
        *,
        state: Mapping[str, Any],
        exclude: Sequence[str] = AGENTCORE_NATIVE_EXCLUSIONS,
    ) -> CheckpointRef:
        check_exclusions(exclude)
        name = uuid4().hex
        try:
            exported = await self.provider._invoke_for(
                handle,
                "export",
                idempotent=False,
                slow=True,
                name=name,
                state=dict(state),
                exclude=list(exclude),
                limits=asdict(self.archive.limits),
            )
            with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.scratch) as directory:
                path = Path(directory) / "checkpoint.tar"
                await self._pull(handle, name, int(exported["size"]), path)
                # The archive was written inside the computer, where the agent can
                # reach it, so check its structure and the exclusions here.
                await self.archive.avalidate(path)
                await asyncio.to_thread(check_excluded, path, self.archive.limits, exclude)
                return await self.store.aput(path)
        finally:
            # Cleanup must never turn a stored checkpoint into an error.
            with suppress(Exception):
                await asyncio.shield(self.provider._invoke_for(handle, "remove", name=name))

    def capture(
        self,
        handle: SandboxHandle,
        *,
        state: Mapping[str, Any],
        exclude: Sequence[str] = AGENTCORE_NATIVE_EXCLUSIONS,
    ) -> CheckpointRef:
        return _sync(self.acapture(handle, state=state, exclude=exclude))

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        name = uuid4().hex
        # The computer is left alone until a request reaches it, so a missing or
        # invalid checkpoint never stops it.
        sent = False
        try:
            async with self.store.aopen_archive(reference) as checkpoint:
                state = await self.archive.avalidate(checkpoint)
                sent = True
                await self._push(handle, name, checkpoint)
            reply = await self.provider._invoke_for(
                handle, "import", idempotent=False, slow=True, name=name, limits=asdict(self.archive.limits)
            )
            if reply["state"] != state:
                raise SandboxError("Restored manifest differs from the verified checkpoint")
            return state
        except BaseException as error:
            # The server checks the handle's identity on every call, and a stale handle
            # must not stop the computer that now holds this session. Otherwise a
            # partially restored computer must never execute another turn.
            stale = isinstance(error, _Refusal) and error.code == "identity"
            if sent and not stale:
                await asyncio.shield(self.provider.astop(handle))
            raise

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        return _sync(self.arestore(handle, reference))
