"""The checkpoint transfer protocol each provider implements, and the default exclusions."""

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from agno.sandbox.base import SandboxHandle
from agno.sandbox.checkpoint import CheckpointRef, CheckpointStore

DEFAULT_NATIVE_EXCLUSIONS = ("native/codex/auth.json", "native/.claude/.credentials.json")


@runtime_checkable
class CheckpointTransfer(Protocol):
    """Moves checkpoints between a sandbox's roots and a store; only the transport is per provider.

    Capture returns a reference to the uploaded archive. Restore fills an empty, unused
    generation and returns the manifest state. The archive format, exclusions and store
    are shared through ``checkpoint``.
    """

    store: CheckpointStore

    async def acapture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef: ...

    def capture(
        self, handle: SandboxHandle, *, state: Mapping[str, Any], exclude: Sequence[str] = DEFAULT_NATIVE_EXCLUSIONS
    ) -> CheckpointRef: ...

    async def arestore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]: ...

    def restore(self, handle: SandboxHandle, reference: CheckpointRef) -> Mapping[str, Any]: ...
