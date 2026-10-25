"""Small sandbox contract; ownership and durable completion belong to AgentOS."""

import asyncio
import json
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Coroutine, Dict, Mapping, Optional, Sequence

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer


class SandboxError(RuntimeError):
    """A sandbox operation failed; callers must reconcile uncertain execution outcomes."""


def _identity(
    session_id: str, agent_id: Optional[str], generation: int, env: Optional[Mapping[str, str]]
) -> Dict[str, str]:
    """Validate per-session create arguments and return a copy of env."""
    if not isinstance(session_id, str) or not session_id or "\x00" in session_id:
        raise ValueError("Sandbox session id must be a nonempty string")
    if agent_id is not None and (not isinstance(agent_id, str) or not agent_id or "\x00" in agent_id):
        raise ValueError("Sandbox agent id must be None or a nonempty string")
    if type(generation) is not int or generation < 1:
        raise ValueError("Sandbox generation must be a positive integer")
    values = dict(env or {})
    for key, value in values.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\x00" in key
            or not isinstance(value, str)
            or "\x00" in value
        ):
            raise ValueError("Sandbox environment must contain valid names and string values")
    return values


def _retention(retain_checkpoints: Optional[int]) -> Optional[int]:
    """Validate how many checkpoints a session keeps; None keeps every one."""
    if retain_checkpoints is not None and (type(retain_checkpoints) is not int or retain_checkpoints < 1):
        raise ValueError("retain_checkpoints must be None or a positive integer")
    return retain_checkpoints


@dataclass(frozen=True)
class SandboxHandle:
    provider_ref: str
    name: str
    agent_id: Optional[str]
    session_id: str
    generation: int
    state: str
    config_digest: str
    # Where the in-container runtime server answers, when the provider exposes one, and the
    # per-container credential it requires. Kept out of repr so handles can be logged.
    runtime_url: Optional[str] = None
    runtime_token: Optional[str] = field(default=None, repr=False)


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: bool = False


def _sync(coro: Coroutine[Any, Any, Any]) -> Any:
    # Inside a running loop (notebook, async server) run on a worker thread with its own loop.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class Sandbox(ABC):
    """A backend for compute, without queue ownership or checkpoint policy.

    Implementations must not retry uncertain commands. Pause and resume are the
    optional warm path: a paused sandbox keeps its files and memory, and resume
    brings the same generation back, so a later turn on the same session need not
    restore a checkpoint. Create never resumes a paused generation; only the caller
    that paused it knows it is whole. Stop and destroy remain the cold path, after
    which recovery needs a new generation. Snapshot, preview and nested-container
    features are not implied.

    Passed as sandbox= on ClaudeAgent or CodexAgent, the whole harness runs in a
    computer from this sandbox each turn; checkpoints, retain_checkpoints, env and
    execution_timeout configure those turns.
    """

    # Where session checkpoints are stored; None uses a local directory that survives only on this host.
    checkpoints: Optional["CheckpointStore"] = None
    # Variables for every harness computer, merged over the harness's model API key from the host.
    env: Optional[Mapping[str, str]] = None
    # Seconds one harness turn may run inside the computer.
    execution_timeout: float = 900
    # Checkpoints each session keeps, newest first; older ones are deleted from the store. None keeps all.
    retain_checkpoints: Optional[int] = 3

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        """Return the transport that moves this sandbox's checkpoints to and from store."""
        raise NotImplementedError(f"{type(self).__name__} cannot checkpoint harness sessions")

    @abstractmethod
    async def acreate(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
    ) -> SandboxHandle: ...

    def create(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
    ) -> SandboxHandle:
        return _sync(self.acreate(session_id, agent_id=agent_id, generation=generation, env=env))

    async def afind(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
        for_create: bool = False,
    ) -> Optional[SandboxHandle]:
        """Reconcile allocation by immutable session generation, including lost create acknowledgements.

        ``for_create`` says a create of the same generation follows at once, so a provider
        may keep compute the lookup itself started for that create to claim.
        """
        raise NotImplementedError("This provider does not support generation reconciliation")

    def find(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
        for_create: bool = False,
    ) -> Optional[SandboxHandle]:
        return _sync(self.afind(session_id, agent_id=agent_id, generation=generation, env=env, for_create=for_create))

    @abstractmethod
    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]: ...

    def get(self, provider_ref: str) -> Optional[SandboxHandle]:
        return _sync(self.aget(provider_ref))

    @abstractmethod
    async def aexec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        max_output_bytes: int = 1_048_576,
        stdin: bytes = b"",
    ) -> ExecResult: ...

    def exec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        max_output_bytes: int = 1_048_576,
        stdin: bytes = b"",
    ) -> ExecResult:
        return _sync(self.aexec(handle, argv, timeout=timeout, max_output_bytes=max_output_bytes, stdin=stdin))

    @abstractmethod
    async def astop(self, handle: SandboxHandle) -> None: ...

    def stop(self, handle: SandboxHandle) -> None:
        _sync(self.astop(handle))

    @abstractmethod
    async def adestroy(self, handle: SandboxHandle) -> None: ...

    def destroy(self, handle: SandboxHandle) -> None:
        _sync(self.adestroy(handle))

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Send one runtime start or poll request and return its JSON reply as stdout.

        A control request, not a command: a lost reply must leave compute as it is.
        Providers with an in-container runtime server override this with a pooled
        connection; the default spawns the runtime over exec, which works on any
        image carrying the package but costs a process per request.
        """
        if operation not in ("start", "poll") or not isinstance(payload, bytes) or len(payload) > 1024 * 1024:
            raise ValueError("Runtime RPC requires start/poll and a payload no larger than 1 MiB")
        try:
            wait = float(json.loads(payload).get("wait", 0) or 0)
        except (ValueError, AttributeError):
            wait = 0.0
        return await self.aexec(
            handle,
            ["python", "-I", "-m", "agno.sandbox.runtime", operation],
            stdin=payload,
            timeout=15 + min(max(wait, 0.0), 30.0),
            max_output_bytes=4 * 1024 * 1024,
        )

    def rpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        return _sync(self.arpc(handle, operation, payload))

    async def apause(self, handle: SandboxHandle) -> None:
        """Freeze a running sandbox, keeping its files, memory and processes.

        The warm path between turns: nothing is lost and nothing needs restoring.
        Providers without a native pause leave this unimplemented; the caller then
        keeps the sandbox running or takes the cold path.
        """
        raise NotImplementedError("This provider does not support pausing compute")

    def pause(self, handle: SandboxHandle) -> None:
        _sync(self.apause(handle))

    async def aresume(self, handle: SandboxHandle) -> SandboxHandle:
        """Unfreeze a paused sandbox and return its running handle.

        The explicit warm step, taken by the caller that paused the sandbox and knows
        its files are complete. Only a paused sandbox resumes. A stopped one has lost
        its files and must be recovered into a new generation from a checkpoint.
        """
        raise NotImplementedError("This provider does not support resuming compute")

    def resume(self, handle: SandboxHandle) -> SandboxHandle:
        return _sync(self.aresume(handle))
