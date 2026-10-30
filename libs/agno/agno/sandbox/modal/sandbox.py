"""Modal Sandboxes: one named Modal sandbox per sandbox generation."""

import asyncio
import base64
import hashlib
import json
import math
import time
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Mapping, Optional, Sequence, Union

from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle, _identity, _retention
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer

_TAG = "agno_"
_RUNNER = (Path(__file__).parent.parent / "_exec.py").read_text()
# Bytes read back from one exec before the transport gives up on it.
_MAX_TRANSPORT = 32 * 1024 * 1024
# Chunk size for exec stdin; Modal buffers at most 16 MiB of unacknowledged input.
_STDIN_CHUNK = 1024 * 1024


class ModalSandbox(Sandbox):
    """Sandbox compute on Modal, one named Modal sandbox per generation.

    Each generation is the sandbox named after its identity inside one Modal app,
    so create is idempotent and a lost create reply is found again by name. Tags
    carry the identity and configuration digest. Modal runs every sandbox in its
    own gVisor container; with ``uid`` set, commands run as that user and the
    workspace and runtime directories are owned by it.

    The image must provide ``python`` with this package installed, ``tar`` and
    ``setpriv``. A string is pulled from a registry with its entrypoint cleared;
    a ``modal.Image`` is used as given.

    ``lifetime`` is Modal's sandbox timeout: at the deadline Modal ends the
    sandbox and a turn still running dies with it. ``execution_timeout`` must be
    shorter, and defaults to 900 seconds or half the lifetime, whichever is shorter.

    Limitation: Modal frees a sandbox's name once it ends, so ``create`` cannot
    tell an ended generation from a new one. This object refuses to recreate a
    generation it stopped itself; callers that lose a computer must recover into
    a new generation, as with every provider, and a coordinator that records
    generations enforces this across replicas.

    Stop and destroy terminate the sandbox; Modal keeps nothing afterwards. Pause
    is not supported, so a warm computer stays running until its window ends.
    Capture cannot freeze the sandbox, so the caller must drain the turn first.
    """

    def __init__(
        self,
        image: Union[str, Any],
        *,
        app_name: str = "agno-sandbox",
        namespace: str = "default",
        cpu: float = 2.0,
        memory_mb: int = 2048,
        lifetime: int = 3600,
        uid: Optional[int] = 1000,
        block_network: bool = False,
        outbound_domain_allowlist: Optional[Sequence[str]] = None,
        region: Optional[str] = None,
        environment_name: Optional[str] = None,
        client: Optional[Any] = None,
        checkpoints: Optional["CheckpointStore"] = None,
        env: Optional[Mapping[str, str]] = None,
        execution_timeout: Optional[float] = None,
        retain_checkpoints: Optional[int] = 3,
    ) -> None:
        try:
            import modal
        except ImportError as error:
            raise ImportError("Install agno[modal-sandbox] to use Modal sandboxes") from error
        if isinstance(image, str):
            if not image or "\x00" in image:
                raise ValueError("Modal sandbox image must be a nonempty registry reference")
        elif not isinstance(image, modal.Image):
            raise ValueError("Modal sandbox image must be a registry reference or a modal.Image")
        for value in (app_name, namespace):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("Modal app name and namespace must be nonempty strings")
        if type(cpu) not in (int, float) or not math.isfinite(cpu) or cpu <= 0:
            raise ValueError("Modal sandbox CPU must be a positive number")
        if type(memory_mb) is not int or memory_mb < 1:
            raise ValueError("Modal sandbox memory must be a positive integer")
        if type(lifetime) is not int or not 60 <= lifetime <= 86400:
            raise ValueError("Modal sandbox lifetime must be between 60 and 86400 seconds")
        if uid is not None and (type(uid) is not int or uid < 1):
            raise ValueError("Modal sandbox uid must be None or a positive integer")
        if block_network and outbound_domain_allowlist:
            raise ValueError("Modal sandboxes cannot both block the network and allow domains")
        if execution_timeout is None:
            execution_timeout = min(900.0, lifetime / 2)
        if not math.isfinite(execution_timeout) or not 0 < execution_timeout < lifetime:
            raise ValueError("Modal execution timeout must be positive and shorter than the lifetime")
        self.image = image
        self.app_name, self.namespace, self.environment_name = app_name, namespace, environment_name
        self.cpu, self.memory_mb, self.lifetime, self.uid = float(cpu), memory_mb, lifetime, uid
        self.block_network = block_network
        self.outbound_domain_allowlist = list(outbound_domain_allowlist) if outbound_domain_allowlist else None
        self.region = region
        self.client = client
        self.checkpoints = checkpoints
        self.env = dict(env) if env is not None else None
        self.execution_timeout = execution_timeout
        self.retain_checkpoints = _retention(retain_checkpoints)
        self._app: Any = None
        self._image: Any = None
        self._image_key: Optional[str] = None
        # One lock per event loop, since each sync call runs on its own.
        self._resolving: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
            weakref.WeakKeyDictionary()
        )
        # Generations this object stopped, with when, oldest first. Recreating one would only
        # start an empty sandbox under a name the caller believes holds files. Dropped once a
        # lifetime has passed, or when the generation is destroyed.
        self._stopped: Dict[str, float] = {}

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        from agno.sandbox.modal.transfer import ModalCheckpointTransfer

        return ModalCheckpointTransfer(self, store)

    def _name(self, session_id: str, agent_id: Optional[str], generation: int) -> str:
        identity = json.dumps([self.namespace, agent_id, session_id, generation])
        return "agno-" + hashlib.sha256(identity.encode()).hexdigest()[:40]

    def _digest(
        self, image_key: str, session_id: str, agent_id: Optional[str], generation: int, env: Mapping[str, str]
    ) -> str:
        data = {
            "image": image_key,
            "app_name": self.app_name,
            "cpu": self.cpu,
            "memory_mb": self.memory_mb,
            "lifetime": self.lifetime,
            "uid": self.uid,
            "block_network": self.block_network,
            "outbound_domain_allowlist": self.outbound_domain_allowlist,
            "region": self.region,
            "agent_id": agent_id,
            "session_id": session_id,
            "generation": generation,
            "env": dict(env),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    async def _resolve(self) -> Any:
        """The app every generation lives in, looked up once and created when missing."""
        if self._image is None:
            # Concurrent first creates wait for one lookup and build instead of each repeating it.
            async with self._resolving.setdefault(asyncio.get_running_loop(), asyncio.Lock()):
                await self._resolve_once()
        return self._app

    async def _resolve_once(self) -> None:
        import modal

        if self._app is None:
            self._app = await modal.App.lookup.aio(
                self.app_name, create_if_missing=True, environment_name=self.environment_name, client=self.client
            )
        if self._image is None:
            if isinstance(self.image, str):
                image = modal.Image.from_registry(self.image).entrypoint([])
                self._image_key = self.image
            else:
                image = self.image
            await image.build.aio(self._app)
            if self._image_key is None:
                self._image_key = image.object_id
            self._image = image

    async def _key(self) -> str:
        await self._resolve()
        assert self._image_key is not None
        return self._image_key

    def _handle(self, sandbox: Any, tags: Mapping[str, str]) -> SandboxHandle:
        if tags.get(_TAG + "namespace") != self.namespace:
            raise SandboxError("Modal sandbox does not belong to this sandbox namespace")
        try:
            agent_id = tags[_TAG + "agent"] or None
            session_id = tags[_TAG + "session"]
            generation = int(tags[_TAG + "generation"])
            return SandboxHandle(
                provider_ref=sandbox.object_id,
                name=self._name(session_id, agent_id, generation),
                agent_id=agent_id,
                session_id=session_id,
                generation=generation,
                state="running",
                config_digest=tags[_TAG + "config"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxError("Modal sandbox has incomplete sandbox identity tags") from error

    async def _running(self, sandbox: Any) -> Optional[SandboxHandle]:
        if await sandbox.poll.aio() is not None:
            return None
        return self._handle(sandbox, await sandbox.get_tags.aio())

    async def _lookup(self, provider_ref: str) -> Optional[Any]:
        import modal

        if not isinstance(provider_ref, str) or not provider_ref.startswith("sb-") or "\x00" in provider_ref:
            raise ValueError("Invalid Modal sandbox reference")
        try:
            return await modal.Sandbox.from_id.aio(provider_ref, client=self.client)
        except modal.exception.NotFoundError:
            return None

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        """The handle for a running sandbox, or None once it has ended."""
        sandbox = await self._lookup(provider_ref)
        return await self._running(sandbox) if sandbox is not None else None

    async def _owned(self, handle: SandboxHandle) -> Optional[Any]:
        """The running Modal sandbox a handle names, refused unless its namespace and identity match."""
        sandbox = await self._lookup(handle.provider_ref)
        current = await self._running(sandbox) if sandbox is not None else None
        if current is None:
            return None
        if (
            current.name != handle.name
            or current.agent_id != handle.agent_id
            or current.session_id != handle.session_id
            or current.generation != handle.generation
            or current.config_digest != handle.config_digest
        ):
            raise SandboxError("Sandbox identity changed; refusing the operation")
        return sandbox

    async def _by_name(self, name: str) -> Optional[Any]:
        import modal

        await self._resolve()
        try:
            return await modal.Sandbox.from_name.aio(
                self.app_name, name, environment_name=self.environment_name, client=self.client
            )
        except modal.exception.NotFoundError:
            return None

    async def afind(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
        for_create: bool = False,
    ) -> Optional[SandboxHandle]:
        values = _identity(session_id, agent_id, generation, env)
        name = self._name(session_id, agent_id, generation)
        sandbox = await self._by_name(name)
        handle = await self._running(sandbox) if sandbox is not None else None
        if handle is not None and handle.config_digest != self._digest(
            await self._key(), session_id, agent_id, generation, values
        ):
            raise SandboxError("Existing generation has different compute configuration")
        return handle

    async def acreate(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
    ) -> SandboxHandle:
        import modal

        values = _identity(session_id, agent_id, generation, env)
        name = self._name(session_id, agent_id, generation)
        self._expire_stopped()
        if name in self._stopped:
            raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
        app = await self._resolve()
        digest = self._digest(await self._key(), session_id, agent_id, generation, values)
        tags = {
            _TAG + "namespace": self.namespace,
            _TAG + "agent": agent_id or "",
            _TAG + "session": session_id,
            _TAG + "generation": str(generation),
            _TAG + "config": digest,
        }
        options: Dict[str, Any] = dict(
            app=app,
            name=name,
            tags=tags,
            image=self._image,
            # Modal passes env as a secret, so values never appear in the sandbox definition.
            env={"HOME": "/runtime", **values},
            timeout=self.lifetime,
            cpu=self.cpu,
            memory=self.memory_mb,
            block_network=self.block_network,
            client=self.client,
        )
        if self.outbound_domain_allowlist:
            options["outbound_domain_allowlist"] = self.outbound_domain_allowlist
        if self.region:
            options["region"] = self.region
        created = False
        sandbox: Any = None
        try:
            sandbox = await modal.Sandbox.create.aio(
                "python", "-I", "-c", "import time; time.sleep(2147483647)", **options
            )
            created = True
        except modal.exception.AlreadyExistsError:
            sandbox = await self._by_name(name)
        except Exception as error:
            # A lost create reply is resolved by the deterministic name.
            sandbox = await self._by_name(name)
            if sandbox is None:
                raise SandboxError(f"Modal sandbox creation failed: {str(error)[:500]}") from error
        current = await self._running(sandbox) if sandbox is not None else None
        if current is None:
            raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
        if current.config_digest != digest:
            raise SandboxError("Sandbox generation already exists with different configuration")
        try:
            await self._prepare(sandbox)
        except BaseException:
            # A sandbox that never held files is safe to remove; one found by name is left to its owner.
            if created:
                await asyncio.shield(self._terminate(sandbox))
            raise
        return current

    async def _prepare(self, sandbox: Any) -> None:
        """Create the workspace and runtime roots, owned by the command user. Idempotent."""
        script = "mkdir -p /workspace /runtime"
        if self.uid is not None:
            script += f" && chown {self.uid}:{self.uid} /workspace /runtime && chmod 0700 /workspace /runtime"
        process = await sandbox.exec.aio("sh", "-c", script, timeout=60)
        error = await process.stderr.read.aio()
        if await process.wait.aio():
            raise SandboxError("Modal sandbox setup failed: " + str(error)[-500:])

    def _argv(self, argv: Sequence[str]) -> list:
        if self.uid is None:
            return list(argv)
        return ["setpriv", f"--reuid={self.uid}", f"--regid={self.uid}", "--clear-groups", "--", *argv]

    async def _process(
        self, handle: SandboxHandle, argv: Sequence[str], *, timeout: float, workdir: str = "/workspace"
    ) -> Any:
        """Start a command as the sandbox user on the sandbox a handle names."""
        if handle.name in self._stopped:
            raise SandboxError("Sandbox is not running")
        sandbox = await self._owned(handle)
        if sandbox is None:
            raise SandboxError("Sandbox is not running")
        return await sandbox.exec.aio(
            *self._argv(argv), timeout=max(1, math.ceil(timeout)), workdir=workdir, text=False
        )

    @staticmethod
    async def _write(process: Any, chunks: AsyncIterator[bytes]) -> None:
        async for chunk in chunks:
            process.stdin.write(chunk)
            await process.stdin.drain.aio()
        process.stdin.write_eof()
        await process.stdin.drain.aio()

    @staticmethod
    async def _read(stream: Any, limit: int) -> bytes:
        chunks, size = [], 0
        async for chunk in stream:
            size += len(chunk)
            if size > limit:
                raise SandboxError("Modal response exceeded the transport output limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Runtime start/poll over exec. A failed or lost reply never touches compute."""
        if operation not in ("start", "poll") or not isinstance(payload, bytes) or len(payload) > 1024 * 1024:
            raise ValueError("Runtime RPC requires start/poll and a payload no larger than 1 MiB")
        try:
            wait = float(json.loads(payload).get("wait", 0) or 0)
        except (ValueError, AttributeError):
            wait = 0.0
        return await self._aexec(
            handle,
            ["python", "-I", "-m", "agno.sandbox.runtime", operation],
            timeout=15 + min(max(wait, 0.0), 30.0),
            max_output_bytes=4 * 1024 * 1024,
            stdin=payload,
            stop_on_failure=False,
        )

    async def aexec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        max_output_bytes: int = 1_048_576,
        stdin: bytes = b"",
    ) -> ExecResult:
        return await self._aexec(handle, argv, timeout=timeout, max_output_bytes=max_output_bytes, stdin=stdin)

    async def _aexec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        max_output_bytes: int = 1_048_576,
        stdin: bytes = b"",
        stop_on_failure: bool = True,
    ) -> ExecResult:
        """Run a command. With ``stop_on_failure`` an uncertain transport outcome stops the
        sandbox; runtime control requests pass False because they exit on their own."""
        if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("Commands must be a nonempty sequence of strings")
        if not math.isfinite(timeout) or timeout <= 0 or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("Timeout must be positive and output limit must be between 1 byte and 4 MiB")
        if not isinstance(stdin, bytes) or len(stdin) > 8 * 1024 * 1024:
            raise ValueError("Command stdin must be bytes no larger than 8 MiB")
        if handle.name in self._stopped:
            raise SandboxError("Sandbox is not running")
        request = json.dumps(
            {
                "argv": list(argv),
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
                "stdin": base64.b64encode(stdin).decode("ascii"),
            }
        ).encode()

        async def run() -> tuple:
            # Modal's exec timeout ends the remote command if this transport is lost.
            process = await self._process(handle, ["python", "-I", "-c", _RUNNER], timeout=timeout + 15)

            async def body() -> AsyncIterator[bytes]:
                for offset in range(0, len(request), _STDIN_CHUNK):
                    yield request[offset : offset + _STDIN_CHUNK]

            _, out, err = await asyncio.gather(
                self._write(process, body()),
                self._read(process.stdout, _MAX_TRANSPORT),
                self._read(process.stderr, _MAX_TRANSPORT),
            )
            return await process.wait.aio(), out, err

        try:
            code, out, err = await asyncio.wait_for(run(), timeout + 30)
        except SandboxError:
            if stop_on_failure:
                await asyncio.shield(self.astop(handle))
            raise
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception) as error:
            if stop_on_failure:
                await asyncio.shield(self.astop(handle))
            if isinstance(error, (asyncio.CancelledError, asyncio.TimeoutError)):
                raise
            raise SandboxError(f"Sandbox command transport failed: {str(error)[:500]}") from error
        try:
            if code:
                raise ValueError(err.decode(errors="replace")[-500:] or f"runner exited with {code}")
            result = ExecResult(**json.loads(out))
        except (TypeError, ValueError) as error:
            if stop_on_failure:
                await self.astop(handle)
            raise SandboxError("Sandbox command transport failed: " + str(error)[:500]) from error
        if stop_on_failure and (result.timed_out or result.output_limited):
            await self.astop(handle)
        return result

    def _expire_stopped(self) -> None:
        now = time.monotonic()
        for name, stopped_at in list(self._stopped.items()):
            if now - stopped_at < self.lifetime:
                break
            del self._stopped[name]

    async def _terminate(self, sandbox: Any) -> None:
        log_debug(f"Terminating Modal sandbox {sandbox.object_id}")
        # Waits for Modal to confirm the sandbox ended, so a following get reports it gone.
        await asyncio.wait_for(sandbox.terminate.aio(wait=True), 120)

    async def astop(self, handle: SandboxHandle) -> None:
        sandbox = await self._owned(handle)
        # Recorded before terminating: a lost terminate reply must still never revive this generation here.
        self._stopped.pop(handle.name, None)
        self._stopped[handle.name] = time.monotonic()
        self._expire_stopped()
        if sandbox is not None:
            await self._terminate(sandbox)

    async def adestroy(self, handle: SandboxHandle) -> None:
        sandbox = await self._owned(handle)
        if sandbox is not None:
            await self._terminate(sandbox)
        # Destroyed, like a removed Docker container, the generation may be created afresh.
        self._stopped.pop(handle.name, None)
