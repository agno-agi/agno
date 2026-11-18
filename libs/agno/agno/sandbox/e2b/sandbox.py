"""E2B sandboxes: one E2B microVM per sandbox generation."""

import asyncio
import base64
import hashlib
import json
import math
import secrets
import shlex
import threading
import weakref
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle, _identity
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer

# Environment variable carrying the sandbox's runtime bearer token.
_TOKEN_ENV = "AGNO_SANDBOX_RUNTIME_TOKEN"
# The template's unprivileged user, which owns /workspace and /runtime.
_USER = "user"
# How long create and resume wait for the runtime server to answer /health.
_RUNTIME_READY_SECONDS = 30.0
# How long create waits for a new computer to appear in E2B's listings, which can lag a create.
_LISTING_SECONDS = 10.0
_LISTING_POLL_SECONDS = 0.5
# E2B grants its user passwordless sudo after the template's own steps, so every create
# strips setuid bits as root and checks none remain before anything runs as that user.
_HARDEN = (
    'find / -xdev -perm -4000 -type f -exec chmod u-s {} + ; test -z "$(find / -xdev -perm -4000 -type f -print -quit)"'
)


async def _close_with_loop(owner: "weakref.ReferenceType[E2BSandbox]", client: Any) -> None:
    loop = asyncio.get_running_loop()
    try:
        while True:
            # This pending timer keeps the closer alive until its loop shuts down and cancels it.
            await asyncio.sleep(3600)
    except GeneratorExit:
        # Collected after its loop closed; no loop is left to close the client on.
        raise
    except BaseException:
        sandbox = owner()
        if sandbox is not None:
            with sandbox._http_lock:
                if sandbox._http.get(loop, (None,))[0] is client:
                    del sandbox._http[loop]
        await client.aclose()
        raise


def _cancel_closers(
    clients: Dict[asyncio.AbstractEventLoop, Tuple[Any, "asyncio.Task[None]"]], lock: threading.Lock
) -> None:
    with lock:
        entries = list(clients.items())
    for loop, (_, task) in entries:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)


class E2BSandbox(Sandbox):
    """Sandbox compute on E2B microVMs, built from a prepared template.

    The template must hold Python with this package installed, ``/workspace`` and
    ``/runtime`` owned by ``user`` with ``/runtime`` as its home, and a root-only
    ``/var/lib/agno-sandbox``; ``e2b_template.py`` in the cookbook builds one. CPU
    and memory come from the template build.

    E2B assigns random sandbox IDs, so each generation is found again by the
    metadata it was created with. A create whose reply was lost is reconciled by
    that metadata; if two computers exist for one generation, the oldest is kept
    and the others are killed. E2B has no atomic allocation, so creates of one
    generation are serialized within this provider, and callers in different
    processes must not create the same generation at once; ``SandboxCoordinator``
    allocates under the session's lease.

    ``lifetime`` is the E2B timeout: E2B kills a running computer when it passes,
    and a turn still running dies with it. ``execution_timeout`` bounds one turn
    and must be shorter; it defaults to 900 seconds or half the lifetime,
    whichever is shorter. Resume restarts the lifetime.

    With ``runtime_port``, the computer runs the runtime server on that port and
    start/poll go to its public E2B URL with a bearer token generated per
    computer. Without it, each start/poll runs the runtime as a command.

    Pause keeps memory, files and processes and does not count against the
    lifetime. Create never resumes a paused generation and the computer never
    resumes on its own. Stop and destroy both kill the computer, which keeps
    nothing. Commands run as ``user`` in ``/workspace``; create strips every
    setuid bit first, since E2B gives that user passwordless sudo. The E2B API
    key stays on the host.
    """

    def __init__(
        self,
        template: str,
        *,
        namespace: str = "default",
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        lifetime: int = 3600,
        allow_internet_access: bool = True,
        runtime_port: Optional[int] = None,
        request_timeout: float = 60,
        checkpoints: Optional["CheckpointStore"] = None,
        env: Optional[Mapping[str, str]] = None,
        execution_timeout: Optional[float] = None,
    ) -> None:
        try:
            import e2b  # noqa: F401
        except ImportError as error:
            raise ImportError("Install agno[e2b-sandbox] to use E2B sandboxes") from error
        for value in (template, namespace):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("E2B template and namespace must be nonempty strings")
        if type(lifetime) is not int or not 60 <= lifetime <= 86400:
            raise ValueError("E2B lifetime must be between 60 and 86400 seconds")
        if runtime_port is not None and (type(runtime_port) is not int or not 1 <= runtime_port <= 65535):
            raise ValueError("Sandbox runtime port must be between 1 and 65535")
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("E2B request timeout must be positive")
        if execution_timeout is None:
            execution_timeout = min(900.0, lifetime / 2)
        if not math.isfinite(execution_timeout) or not 0 < execution_timeout < lifetime:
            raise ValueError("E2B execution timeout must be positive and shorter than the lifetime")
        self.template = template
        self.namespace = namespace
        self.lifetime = lifetime
        self.allow_internet_access = allow_internet_access
        self.runtime_port = runtime_port
        self.checkpoints = checkpoints
        self.env = dict(env) if env is not None else None
        self.execution_timeout = execution_timeout
        self._options: Dict[str, Any] = {"request_timeout": request_timeout}
        if api_key is not None:
            self._options["api_key"] = api_key
        if domain is not None:
            self._options["domain"] = domain
        # Connections to running computers, so each command does not reconnect.
        self._connections: Dict[str, Any] = {}
        # Creates of one generation run one at a time here, from any thread or event loop.
        self._create_locks: Dict[str, List[Any]] = {}
        self._create_locks_guard = threading.Lock()
        # The computer this provider kept for each generation, checked directly when a listing omits it.
        self._known: Dict[str, str] = {}
        # One pooled HTTP client per event loop for the runtime server, so requests reuse TLS connections.
        self._http: Dict[asyncio.AbstractEventLoop, Tuple[Any, "asyncio.Task[None]"]] = {}
        self._http_lock = threading.Lock()
        weakref.finalize(self, _cancel_closers, self._http, self._http_lock)

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        from agno.sandbox.e2b.transfer import E2BCheckpointTransfer

        return E2BCheckpointTransfer(self, store)

    def _name(self, session_id: str, agent_id: Optional[str], generation: int) -> str:
        identity = json.dumps([self.namespace, agent_id, session_id, generation])
        return "agno-" + hashlib.sha256(identity.encode()).hexdigest()[:40]

    def _digest(self, session_id: str, agent_id: Optional[str], generation: int, env: Mapping[str, str]) -> str:
        data = {
            "template": self.template,
            "lifetime": self.lifetime,
            "allow_internet_access": self.allow_internet_access,
            "runtime_port": self.runtime_port,
            "agent_id": agent_id,
            "session_id": session_id,
            "generation": generation,
            "env": dict(env),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _runtime_url(self, sandbox_id: str, sandbox_domain: Optional[str], port: Optional[str]) -> Optional[str]:
        if not port:
            return None
        from e2b.connection_config import ConnectionConfig

        config = ConnectionConfig(**self._options)
        return "https://" + config.get_host(sandbox_id, sandbox_domain or config.domain, int(port))

    def _handle(self, info: Any) -> SandboxHandle:
        metadata = info.metadata if isinstance(info.metadata, dict) else {}
        if metadata.get("namespace") != self.namespace:
            raise SandboxError("E2B sandbox does not belong to this sandbox namespace")
        try:
            return SandboxHandle(
                provider_ref=info.sandbox_id,
                name=metadata["name"],
                agent_id=metadata["agent"] or None,
                session_id=metadata["session"],
                generation=int(metadata["generation"]),
                state=str(info.state),
                config_digest=metadata["config"],
                runtime_url=self._runtime_url(info.sandbox_id, info.sandbox_domain, metadata.get("runtime")),
                runtime_token=metadata.get("token") or None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxError("E2B sandbox has incomplete sandbox identity metadata") from error

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        if not isinstance(provider_ref, str) or not provider_ref or "\x00" in provider_ref or "/" in provider_ref:
            raise ValueError("Invalid E2B sandbox reference")
        from e2b import AsyncSandbox, SandboxNotFoundException

        try:
            info = await AsyncSandbox.get_info(provider_ref, **self._options)
        except SandboxNotFoundException:
            return None
        return self._handle(info)

    async def _listed(self, name: str) -> List[Any]:
        from e2b import AsyncSandbox, SandboxQuery, SandboxState

        paginator = AsyncSandbox.list(
            query=SandboxQuery(
                metadata={"namespace": self.namespace, "name": name},
                state=[SandboxState.RUNNING, SandboxState.PAUSED],
            ),
            **self._options,
        )
        found: List[Any] = []
        while paginator.has_next:
            found.extend(await paginator.next_items())
        return found

    async def _await_listed(self, name: str, sandbox_id: Optional[str]) -> Optional[List[Any]]:
        """The first listing that shows ``sandbox_id``, or any computer of the generation when it is unknown.

        Listings lag a create and successive ones can disagree, so the caller decides from this one.
        """
        deadline = asyncio.get_running_loop().time() + _LISTING_SECONDS
        while True:
            found = await self._listed(name)
            if any(sandbox_id in (None, info.sandbox_id) for info in found):
                return found
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(_LISTING_POLL_SECONDS)

    async def _lookup(self, name: str, found: Optional[List[Any]] = None) -> Optional[SandboxHandle]:
        """The computer of a generation, killing any duplicates a lost create reply left."""
        from e2b import AsyncSandbox, SandboxNotFoundException

        if found is None:
            found = await self._listed(name)
        found = list(found)
        known = self._known.get(name)
        if known is not None and all(info.sandbox_id != known for info in found):
            # Listings can omit a computer this provider already handed out, so ask for it directly.
            try:
                info = await AsyncSandbox.get_info(known, **self._options)
            except SandboxNotFoundException:
                info = None
            if info is not None and isinstance(info.metadata, dict) and info.metadata.get("name") == name:
                found.append(info)
            elif self._known.get(name) == known:
                del self._known[name]
        if not found:
            return None
        found.sort(key=lambda info: (info.started_at, info.sandbox_id))
        for duplicate in found[1:]:
            log_debug(f"Killing duplicate E2B sandbox {duplicate.sandbox_id} for generation {name}")
            await AsyncSandbox.kill(duplicate.sandbox_id, **self._options)
        # Listings omit nothing the handle needs, but read the kept one fresh so its state is current.
        current = await self.aget(found[0].sandbox_id)
        if current is not None:
            self._known[name] = current.provider_ref
        return current

    async def _owned(self, handle: SandboxHandle) -> Optional[SandboxHandle]:
        current = await self.aget(handle.provider_ref)
        if current is not None and (
            current.name != handle.name
            or current.agent_id != handle.agent_id
            or current.session_id != handle.session_id
            or current.generation != handle.generation
            or current.config_digest != handle.config_digest
        ):
            raise SandboxError("Sandbox identity changed; refusing the operation")
        return current

    async def _connection(self, handle: SandboxHandle) -> Any:
        """A connection to the running computer a handle names, and no other.

        Connecting resumes a paused computer, so this checks it is running first.
        Only the caller that paused a generation resumes it, so nothing pauses it
        between the check and the connect.
        """
        current = await self._owned(handle)
        if current is not None and current.state == "paused":
            raise SandboxError("Sandbox is paused; resume it before running commands")
        if current is None or current.state != "running":
            self._connections.pop(handle.provider_ref, None)
            raise SandboxError("Sandbox is not running")
        connection = self._connections.get(handle.provider_ref)
        if connection is None:
            from e2b import AsyncSandbox

            connection = await AsyncSandbox.connect(handle.provider_ref, **self._options)
            self._connections[handle.provider_ref] = connection
        return connection

    async def afind(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
        for_create: bool = False,
    ) -> Optional[SandboxHandle]:
        # A lookup never starts compute here, so there is nothing for a following create to claim.
        values = _identity(session_id, agent_id, generation, env)
        handle = await self._lookup(self._name(session_id, agent_id, generation))
        if handle is not None and handle.config_digest != self._digest(session_id, agent_id, generation, values):
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
        values = _identity(session_id, agent_id, generation, env)
        if _TOKEN_ENV in values:
            raise ValueError("The runtime token is generated per computer; do not set it in env")
        name = self._name(session_id, agent_id, generation)
        async with self._generation_lock(name):
            return await self._acreate(name, session_id, agent_id, generation, values)

    @asynccontextmanager
    async def _generation_lock(self, name: str) -> AsyncIterator[None]:
        with self._create_locks_guard:
            entry = self._create_locks.setdefault(name, [threading.Lock(), 0])
            entry[1] += 1
        try:
            # Polled rather than blocking, so a cancelled waiter never takes the lock afterwards.
            while not entry[0].acquire(blocking=False):
                await asyncio.sleep(0.05)
            try:
                yield
            finally:
                entry[0].release()
        finally:
            with self._create_locks_guard:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._create_locks[name]

    async def _kill_created(self, name: str, sandbox_id: str) -> None:
        """Kill a computer this create made but cannot hand out, so it never runs unowned."""
        from e2b import AsyncSandbox

        if self._known.get(name) == sandbox_id:
            del self._known[name]
        try:
            await asyncio.shield(AsyncSandbox.kill(sandbox_id, **self._options))
        except Exception as error:
            log_warning(f"Could not kill unlisted E2B sandbox {sandbox_id}: {error}")

    async def _acreate(
        self, name: str, session_id: str, agent_id: Optional[str], generation: int, values: Mapping[str, str]
    ) -> SandboxHandle:
        digest = self._digest(session_id, agent_id, generation, values)
        created_id: Optional[str] = None
        current = await self._lookup(name)
        if current is None:
            from e2b import AsyncSandbox

            metadata = {
                "namespace": self.namespace,
                "name": name,
                "agent": agent_id or "",
                "session": session_id,
                "generation": str(generation),
                "config": digest,
            }
            if self.runtime_port is not None:
                metadata["runtime"] = str(self.runtime_port)
                metadata["token"] = secrets.token_urlsafe(32)
            from e2b import AuthenticationException, InvalidArgumentException, NotFoundException, RateLimitException

            found: Optional[List[Any]] = None
            try:
                created = await AsyncSandbox.create(
                    template=self.template,
                    timeout=self.lifetime,
                    metadata=metadata,
                    envs=dict(values),
                    allow_internet_access=self.allow_internet_access,
                    lifecycle={"on_timeout": "kill", "auto_resume": False},
                    **self._options,
                )
                created_id = created.sandbox_id
            except (AuthenticationException, InvalidArgumentException, NotFoundException, RateLimitException) as error:
                # E2B refused the create, so no computer exists to find.
                raise SandboxError(f"E2B creation failed: {str(error)[:500] or type(error).__name__}") from error
            except Exception as error:
                # The SDK never resends a create, but a lost reply may still have made one.
                found = await self._await_listed(name, None)
                if found is None:
                    raise SandboxError(f"E2B creation failed: {str(error)[:500] or type(error).__name__}") from error
            try:
                # Listings lag a create, so wait for this one before choosing the oldest.
                if created_id is not None:
                    found = await self._await_listed(name, created_id)
                current = await self._lookup(name, found) if found is not None else None
            except BaseException:
                if created_id is not None:
                    await self._kill_created(name, created_id)
                raise
            if current is None:
                if created_id is not None:
                    await self._kill_created(name, created_id)
                raise SandboxError("E2B sandbox did not appear in listings after creation")
        try:
            if current.config_digest != digest:
                raise SandboxError("Sandbox generation already exists with different configuration")
            if current.state == "paused":
                # Only the owner knows whether this is a warm pause or a restore that died halfway,
                # so create never revives it: the owner calls resume, anyone else destroys.
                raise SandboxError("Sandbox generation is paused; resume it or destroy it")
            if current.state != "running":
                raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
            await self._harden(current)
            if self.runtime_port is not None:
                await self._start_runtime(current)
        except BaseException:
            # Only a computer this call made is killed; an existing generation may be in use.
            if created_id is not None and current.provider_ref == created_id:
                await self._kill_created(name, created_id)
            raise
        return current

    async def _harden(self, handle: SandboxHandle) -> None:
        """Leave the agent's user no setuid path to root; a computer that cannot be hardened is killed."""
        from e2b import CommandExitException

        connection = await self._connection(handle)
        try:
            await connection.commands.run(_HARDEN, user="root", cwd="/", timeout=60)
        except Exception as error:
            stderr = error.stderr if isinstance(error, CommandExitException) else str(error)
            await asyncio.shield(self.astop(handle))
            raise SandboxError(
                "Could not remove privilege escalation from the E2B sandbox: " + stderr[-500:]
            ) from error

    async def _start_runtime(self, handle: SandboxHandle) -> None:
        """Start the runtime server once per computer and wait until it answers."""
        if handle.runtime_url is None or handle.runtime_token is None:
            raise SandboxError("Sandbox generation does not publish its runtime port")
        if await self._healthy(handle):
            return
        connection = await self._connection(handle)
        # flock keeps a repeated create from starting a second supervisor on the same port.
        command = shlex.join(
            ["flock", "-n", "/tmp/agno-runtime.lock"]
            + ["python", "-I", "-m", "agno.sandbox.runtime", "supervise", "--port", str(self.runtime_port)]
        )
        await connection.commands.run(
            command,
            background=True,
            user=_USER,
            cwd="/workspace",
            envs={_TOKEN_ENV: handle.runtime_token},
            timeout=0,
        )
        deadline = asyncio.get_running_loop().time() + _RUNTIME_READY_SECONDS
        while not await self._healthy(handle):
            if asyncio.get_running_loop().time() >= deadline:
                raise SandboxError("Sandbox runtime server did not become ready")
            await asyncio.sleep(0.25)

    @staticmethod
    def _headers(handle: SandboxHandle) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if handle.runtime_token:
            headers["Authorization"] = "Bearer " + handle.runtime_token
        return headers

    def _http_client(self) -> Any:
        """One pooled client per event loop, closed when that loop shuts down."""
        import httpx

        loop = asyncio.get_running_loop()
        with self._http_lock:
            for stale in [item for item in self._http if item.is_closed()]:
                del self._http[stale]
            entry = self._http.get(loop)
            if entry is None:
                limits = httpx.Limits(max_connections=4096, max_keepalive_connections=1024)
                client = httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(15.0, read=60.0))
                closer = loop.create_task(_close_with_loop(weakref.ref(self), client))
                entry = self._http[loop] = (client, closer)
        return entry[0]

    async def _healthy(self, handle: SandboxHandle) -> bool:
        import httpx

        assert handle.runtime_url is not None
        try:
            response = await self._http_client().get(
                handle.runtime_url + "/health", headers=self._headers(handle), timeout=5.0
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Runtime start/poll over the computer's runtime server when it has one, else over exec.

        A failed or lost reply never touches compute: the coordinator reconciles.
        """
        if operation not in ("start", "poll") or not isinstance(payload, bytes) or len(payload) > 1024 * 1024:
            raise ValueError("Runtime RPC requires start/poll and a payload no larger than 1 MiB")
        if handle.runtime_url is None:
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
        import httpx

        try:
            response = await self._http_client().post(
                handle.runtime_url + "/" + operation, content=payload, headers=self._headers(handle)
            )
        except httpx.HTTPError as error:
            raise SandboxError(f"Sandbox runtime request failed: {str(error) or type(error).__name__}") from error
        body = response.text[: 4 * 1024 * 1024]
        if response.status_code != 200:
            return ExecResult(exit_code=1, stdout="", stderr=body)
        return ExecResult(exit_code=0, stdout=body, stderr="")

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
        """Run a command. With ``stop_on_failure`` an uncertain transport outcome kills the
        computer, since a lost connection does not end the command inside it; runtime control
        requests pass False because they exit on their own."""
        if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("Commands must be a nonempty sequence of strings")
        if not math.isfinite(timeout) or timeout <= 0 or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("Timeout must be positive and output limit must be between 1 byte and 4 MiB")
        if not isinstance(stdin, bytes) or len(stdin) > 8 * 1024 * 1024:
            raise ValueError("Command stdin must be bytes no larger than 8 MiB")
        from e2b import CommandExitException

        connection = await self._connection(handle)
        request = json.dumps(
            {
                "argv": list(argv),
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
                "stdin": base64.b64encode(stdin).decode("ascii"),
            }
        ).encode()
        # The command API has no stdin, so the runner's request is staged as a file first.
        # Nothing runs until the command is sent, so a failed upload leaves compute as it is.
        staged = f"/tmp/agno-exec-{uuid4().hex}.json"
        await connection.files.write(staged, request, user=_USER)
        quoted = shlex.quote(staged)
        command = (
            shlex.join(["python", "-I", "-m", "agno.sandbox._exec"])
            + f" < {quoted}; status=$?; rm -f {quoted}; exit $status"
        )
        try:
            try:
                reply = await connection.commands.run(command, user=_USER, cwd="/workspace", timeout=timeout + 15)
            except CommandExitException as exited:
                reply = exited
        except BaseException as error:
            # The command may still be running inside the computer. Kill compute to bound
            # it; checkpoint recovery belongs to the coordinator.
            if stop_on_failure:
                await asyncio.shield(self.astop(handle))
            if isinstance(error, Exception):
                raise SandboxError(
                    f"Sandbox command transport failed: {str(error)[:500] or type(error).__name__}"
                ) from error
            raise
        try:
            if reply.exit_code:
                raise ValueError(reply.stderr[-500:] or f"runner exited with {reply.exit_code}")
            result = ExecResult(**json.loads(reply.stdout))
        except (TypeError, ValueError) as error:
            if stop_on_failure:
                await self.astop(handle)
            raise SandboxError("Sandbox command transport failed: " + str(error)[:500]) from error
        if stop_on_failure and (result.timed_out or result.output_limited):
            await self.astop(handle)
        return result

    async def apause(self, handle: SandboxHandle) -> None:
        from e2b import AsyncSandbox

        current = await self._owned(handle)
        if current is not None and current.state == "paused":
            return
        if current is None or current.state != "running":
            raise SandboxError("Only a running sandbox can be paused")
        self._connections.pop(handle.provider_ref, None)
        await AsyncSandbox.pause(handle.provider_ref, **self._options)

    async def aresume(self, handle: SandboxHandle) -> SandboxHandle:
        from e2b import AsyncSandbox

        current = await self._owned(handle)
        if current is not None and current.state == "running":
            return current
        if current is None or current.state != "paused":
            raise SandboxError("Sandbox is not paused; recovery requires a new generation")
        await AsyncSandbox.connect(handle.provider_ref, timeout=self.lifetime, **self._options)
        current = await self._owned(handle)
        if current is None or current.state != "running":
            raise SandboxError("E2B resume did not leave the sandbox running")
        if self.runtime_port is not None:
            await self._start_runtime(current)
        return current

    async def astop(self, handle: SandboxHandle) -> None:
        from e2b import AsyncSandbox

        self._connections.pop(handle.provider_ref, None)
        if self._known.get(handle.name) == handle.provider_ref:
            del self._known[handle.name]
        if await self._owned(handle) is None:
            return
        log_debug(f"Killing E2B sandbox {handle.provider_ref}")
        await AsyncSandbox.kill(handle.provider_ref, **self._options)

    async def adestroy(self, handle: SandboxHandle) -> None:
        # A killed E2B computer keeps nothing, so destroy and stop are the same.
        await self.astop(handle)
