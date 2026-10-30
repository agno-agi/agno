"""Checkpoint transport for Modal sandboxes, through tar over exec streams."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Mapping, Optional, Sequence

from agno.sandbox.base import SandboxError, SandboxHandle, _sync
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointContentError,
    CheckpointRef,
    CheckpointStore,
    _combine_exports,
    _split_archive,
    _thread,
)
from agno.sandbox.modal.sandbox import _STDIN_CHUNK, ModalSandbox
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS

# Generous for a large workspace; Modal's exec timeout still ends a stalled transfer.
_TRANSFER_TIMEOUT = 900
# Each root as a tar whose top-level entry is the root's own name, like docker cp.
_EXPORTS = {"workspace": ("/", "workspace"), "native": ("/runtime", "native")}
_IMPORTS = {"workspace": "/workspace", "native": "/runtime/native"}


class ModalCheckpointTransfer:
    """Stream checkpoints in and out of Modal sandboxes with tar over exec.

    Implements the ``CheckpointTransfer`` protocol. Capture streams one tar per
    root out of the sandbox, bounded by the archive's byte limit, and the host
    repacks and validates it before storing. Restore validates the stored
    archive on the host, checks the target generation is empty, and streams a
    repacked tar per root in; a partially restored sandbox is stopped. Modal
    cannot freeze a sandbox, so the caller must drain the turn before capture.
    ``scratch`` holds unencrypted archives in transit and must be coordinator-private.
    """

    def __init__(
        self,
        provider: ModalSandbox,
        store: CheckpointStore,
        *,
        archive: Optional[CheckpointArchive] = None,
        scratch: Optional[Path] = None,
    ) -> None:
        self.provider, self.store, self.scratch = provider, store, scratch
        self.archive = archive or CheckpointArchive()

    async def _finish(self, process: Any, what: str) -> None:
        error = await self.provider._read(process.stderr, 1024 * 1024)
        if await process.wait.aio():
            raise SandboxError(f"Modal checkpoint {what} failed: " + error.decode(errors="replace")[-1000:])

    async def _export(self, handle: SandboxHandle, root: str, destination: Path) -> None:
        directory, name = _EXPORTS[root]
        process = await self.provider._process(
            handle, ["tar", "-C", directory, "-cf", "-", name], timeout=_TRANSFER_TIMEOUT, workdir="/"
        )
        limit = self.archive.limits.max_bytes
        with destination.open("xb") as output:
            size = 0
            async for chunk in process.stdout:
                size += len(chunk)
                if size > limit:
                    raise CheckpointContentError("Checkpoint transfer exceeds its byte limit")
                await _thread(output.write, chunk)
        await self._finish(process, "export")

    async def _import(self, handle: SandboxHandle, root: str, source: Path) -> None:
        process = await self.provider._process(
            handle,
            ["tar", "-x", "-p", "--no-same-owner", "-f", "-", "-C", _IMPORTS[root]],
            timeout=_TRANSFER_TIMEOUT,
            workdir="/",
        )

        async def chunks() -> AsyncIterator[bytes]:
            with source.open("rb") as stream:
                while data := await _thread(stream.read, _STDIN_CHUNK):
                    yield data

        await asyncio.gather(self.provider._write(process, chunks()), self._finish(process, "import"))

    async def acapture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef:
        ready = await self.provider.aexec(handle, ["mkdir", "-p", "/runtime/native"])
        if ready.exit_code:
            raise SandboxError("Could not prepare the native state directory")
        with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.scratch) as directory:
            root = Path(directory)
            exports = {name: root / (name + ".tar") for name in _EXPORTS}
            for name, path in exports.items():
                await self._export(handle, name, path)
            # The exports were written inside the sandbox, where the agent can reach
            # them, so they are repacked and validated here before upload.
            await _thread(_combine_exports, self.archive, exports, root / "checkpoint.tar", state, exclude)
            return await self.store.aput(root / "checkpoint.tar")

    def capture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef:
        return _sync(self.acapture(handle, state=state, exclude=exclude))

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        with tempfile.TemporaryDirectory(prefix=".import-", dir=self.scratch) as directory:
            root = Path(directory)
            async with self.store.aopen_archive(reference) as checkpoint:
                state, native_mode = await _thread(_split_archive, self.archive, checkpoint, root)
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
            try:
                for name in _IMPORTS:
                    await self._import(handle, name, root / (name + ".tar"))
            except BaseException:
                # A partially restored sandbox must never execute another turn.
                await asyncio.shield(self.provider.astop(handle))
                raise
        return state

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]:
        return _sync(self.arestore(handle, reference))
