"""Provider boundary for session-bound execution environments."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SandboxSpec:
    sandbox_id: str
    generation: int
    image: str
    env: Dict[str, str] = field(default_factory=dict, repr=False)
    command: List[str] = field(default_factory=lambda: ["python", "-m", "agno.sandbox.runtime"])
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 512

    @property
    def name(self) -> str:
        from uuid import UUID

        # A provider name is an internal identifier, never caller-controlled text.
        identifier = UUID(self.sandbox_id).hex
        if self.generation < 1:
            raise ValueError("Sandbox generation must be positive")
        return f"agno-sandbox-{identifier}-{self.generation}"


@dataclass(frozen=True)
class SandboxHandle:
    provider_ref: str
    url: str
    status: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(ABC):
    """Async providers with matching synchronous entry points."""

    name: str

    @abstractmethod
    async def acreate(self, spec: SandboxSpec) -> SandboxHandle: ...

    @abstractmethod
    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]: ...

    @abstractmethod
    async def adestroy(self, handle: SandboxHandle) -> None: ...

    @abstractmethod
    async def aexec(self, handle: SandboxHandle, cmd: List[str], timeout: float = 60) -> ExecResult: ...

    async def apause(self, handle: SandboxHandle) -> Optional[str]:
        return None

    async def aresume(self, handle: SandboxHandle, snapshot_ref: Optional[str] = None) -> SandboxHandle:
        raise NotImplementedError(f"{self.name} does not support pause/resume")

    async def aexpose(self, handle: SandboxHandle, port: int = 7777) -> str:
        if port != 7777:
            raise NotImplementedError("Only the runtime port is exposed")
        return handle.url

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        return _sync(self.acreate(spec))

    def get(self, provider_ref: str) -> Optional[SandboxHandle]:
        return _sync(self.aget(provider_ref))

    def destroy(self, handle: SandboxHandle) -> None:
        _sync(self.adestroy(handle))

    def exec(self, handle: SandboxHandle, cmd: List[str], timeout: float = 60) -> ExecResult:
        return _sync(self.aexec(handle, cmd, timeout))

    def pause(self, handle: SandboxHandle) -> Optional[str]:
        return _sync(self.apause(handle))

    def resume(self, handle: SandboxHandle, snapshot_ref: Optional[str] = None) -> SandboxHandle:
        return _sync(self.aresume(handle, snapshot_ref))

    def expose(self, handle: SandboxHandle, port: int = 7777) -> str:
        return _sync(self.aexpose(handle, port))


def _sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise RuntimeError("Use the async method inside a running event loop")
