"""Vercel sandboxes: one Vercel microVM per session generation, reached through a guest guard that runs as root."""

import asyncio
import base64
import hashlib
import importlib
import json
import math
import re
import secrets
import sys
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union
from uuid import uuid4

from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle, _identity, _retention
from agno.sandbox.checkpoint import CheckpointContentError, _drain
from agno.sandbox.vercel.guard import (
    INBOX,
    MANAGED_ENVIRONMENT,
    MAX_MARKER,
    MAX_STAGED,
    PYTHON,
    REFUSAL_PREFIX,
    REFUSED,
    STAGED_UID,
    source_digest,
)
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer

# The image supplies uv; bootstrap installs the guest Python version below.
IMAGE = "vercel/sandbox/python:3.14"
GUEST_PYTHON = "3.12"
# Guest package pins follow the shared Dockerfile; transitive dependencies remain unpinned.
NATIVE_PINS = ("claude-agent-sdk==0.2.165", "openai-codex==0.162.1", "sqlalchemy==2.0.52")
_BOOTSTRAP = "/opt/agno"
_WHEEL_STAGE = "/tmp/agno-bootstrap"
_UV_ENVIRONMENT = (
    f"UV_PYTHON_INSTALL_DIR={_BOOTSTRAP}/python",
    f"UV_CACHE_DIR={_BOOTSTRAP}/uvcache",
    "HOME=/root",
)
# Bounds on each root step of the bootstrap, in seconds of the service's own kill timer.
_QUICK_STEP = 120.0
_VENV_STEP = 600.0
_INSTALL_STEP = 1500.0
_MAX_LISTED = 500
_CLOSE_GRACE = 10.0  # how long a cancelled operation waits for its client to finish closing
_MEMORY_PER_VCPU = 2048

# The runner enforces the caller's timeout itself. Counted from that timeout, the service kills the
# guard after _KILL_GRACE and the host stops waiting after _HOST_GRACE.
_KILL_GRACE = 10.0
_HOST_GRACE = 20.0
# A runtime start or poll answers within this long, plus the poll's own wait (as the base default).
_RPC_BASE_SECONDS = 15.0
_READY_SECONDS = 15.0
# A guard reply carries at most a checkpoint's state, which the archive allows up to 1 MiB.
_REPLY_LIMIT = 2 * 1024 * 1024
_CHUNK = 8 * 1024 * 1024
_STDERR_LIMIT = 64 * 1024
_ENDED = ("stopped", "stopping", "failed", "aborted")
_STATES = {**dict.fromkeys(_ENDED, "exited"), "pending": "created", "snapshotting": "created"}
_RESULT_KEYS = {"exit_code", "stdout", "stderr", "timed_out", "output_limited"}


class _OutputOverflow(Exception):
    pass


class _NotSent(SandboxError):
    """A request failed before anything reached the computer, so the computer is as it was."""


class _Capture:
    """Text sink that never holds more than ``limit`` characters.

    Standard output must fit what the runner can produce, so overflow is a protocol failure;
    standard error is only diagnostics and is cut short.
    """

    def __init__(self, limit: int, *, strict: bool) -> None:
        self.limit, self.strict, self.size = limit, strict, 0
        self.parts: List[str] = []

    def write(self, text: str) -> int:
        self.size += len(text)
        if self.size <= self.limit:
            self.parts.append(text)
        elif self.strict:
            raise _OutputOverflow(f"output exceeds {self.limit} characters")
        return len(text)

    def flush(self) -> None:
        pass

    def text(self) -> str:
        return "".join(self.parts)


def _new_client(options: Any) -> Any:
    """A Vercel SDK client owned by one operation; the SDK loads only here."""
    try:
        sdk = importlib.import_module("vercel.sandbox")
    except ImportError as error:
        raise ImportError(
            "Install the Vercel Sandbox Python SDK (vercel-sandbox, Python 3.10+) to use VercelSandbox"
        ) from error
    return sdk.SandboxClient.create(options=options)


def _sdk() -> Any:
    """The SDK module, once a client exists; its types are needed to build a create and a listing request."""
    return importlib.import_module("vercel.sandbox")


@lru_cache(maxsize=1)
def _host_digest() -> str:
    # Once per process: the modules this process imported cannot change under it.
    import agno

    return source_digest(Path(agno.__file__).parent)


_ABANDONED_CLOSES: Set["asyncio.Future[None]"] = set()


async def _close(client: Any) -> None:
    # SDK close cannot be restarted. Shield it, bound the wait on cancellation, and preserve the caller's error.
    task = asyncio.ensure_future(client.aclose())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        failure = await _wait_for_close(task)
        if failure is not None:
            log_warning(f"Could not close the Vercel SDK client: {_describe(failure)}")
        raise
    except Exception as error:
        log_warning(f"Could not close the Vercel SDK client: {_describe(error)}")


async def _wait_for_close(task: "asyncio.Future[None]") -> Optional[BaseException]:
    """Wait for a close its caller's cancellation interrupted; return its failure, or give up after the bound."""
    loop = asyncio.get_running_loop()
    end = loop.time() + _CLOSE_GRACE
    while not task.done():
        remaining = end - loop.time()
        if remaining <= 0:
            log_warning("The Vercel SDK client is still closing; no longer waiting for it")
            _ABANDONED_CLOSES.add(task)  # a pending task nothing references can be collected mid-close
            task.add_done_callback(_abandoned_close_ended)
            return None
        with suppress(asyncio.CancelledError):  # a repeated cancellation must not cut the wait short
            await asyncio.wait({task}, timeout=remaining)
    return None if task.cancelled() else task.exception()


def _abandoned_close_ended(task: "asyncio.Future[None]") -> None:
    _ABANDONED_CLOSES.discard(task)
    if not task.cancelled():
        task.exception()  # retrieved, so a late failure is not reported as one nobody saw


def _credentials_failed(error: BaseException) -> bool:
    """The SDK's own credentials error, raised while it resolves credentials, which it does before it sends anything.

    Looked up, not imported: a client already loaded the SDK, and an import here could mask the error.
    """
    sdk = sys.modules.get("vercel.sandbox")
    return sdk is not None and isinstance(error, sdk.SandboxCredentialsError)


def _describe(error: BaseException) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "timed out waiting for the reply"
    return f"{type(error).__name__}: {error}"


def _not_found(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 404


def _bound(handle: SandboxHandle) -> Tuple[str, str]:
    """The sandbox name and the exact session a handle was issued for."""
    physical, _, session = handle.name.partition("/")
    if (
        not physical
        or physical != handle.provider_ref
        or not session
        or "/" in session
        or "\x00" in session
        or session != session.strip()
    ):
        raise ValueError("Sandbox handle does not name a Vercel sandbox and its session")
    return physical, session


def _created_key(sandbox: Any) -> float:
    created = getattr(sandbox, "created_at", None)
    if created is None:
        return 0.0
    return float(created.timestamp() if hasattr(created, "timestamp") else created)


def _result(text: str) -> ExecResult:
    data = json.loads(text)
    if (
        not isinstance(data, dict)
        or set(data) != _RESULT_KEYS
        or type(data["exit_code"]) is not int
        or not isinstance(data["stdout"], str)
        or not isinstance(data["stderr"], str)
        or type(data["timed_out"]) is not bool
        or type(data["output_limited"]) is not bool
    ):
        raise ValueError("invalid command result")
    return ExecResult(**data)


class VercelSandbox(Sandbox):
    """Sandbox compute on Vercel Sandbox microVMs, non-persistent and reached through a root guard.

    A handle names one sandbox and the exact session it was issued for (``name`` is
    ``"<sandbox>/<session>"``). Every operation looks the sandbox up without resuming it and acts
    only on that session, so a replaced or stopped session is never run on, replayed on or stopped.
    Each public call makes its own SDK client and closes it before returning.

    ``lifetime`` is the server-side execution limit of one computer, and ``execution_timeout``
    bounds one turn inside it; neither bounds how many computers exist. ``vcpus`` sizes the computer
    (memory follows). ``wheel`` is an Agno wheel built from the host's own checkout; without it the guest
    attempts to install the host's release, which must hold exactly the host's source (the release-install
    route is not yet verified). ``options`` are the SDK's
    service options, such as credentials. ``retain_checkpoints`` is the number of checkpoints kept per
    session (three by default); ``None`` keeps every checkpoint. Pause and resume are not supported.
    """

    def __init__(
        self,
        *,
        namespace: str = "default",
        lifetime: int = 1800,
        vcpus: int = 1,
        wheel: Optional[Union[str, Path]] = None,
        options: Optional[Any] = None,
        checkpoints: Optional["CheckpointStore"] = None,
        env: Optional[Mapping[str, str]] = None,
        execution_timeout: Optional[float] = None,
        retain_checkpoints: Optional[int] = 3,
    ) -> None:
        if not isinstance(namespace, str) or not namespace or "\x00" in namespace:
            raise ValueError("Vercel namespace must be a nonempty string")
        if type(lifetime) is not int or not 60 <= lifetime <= 86400:
            raise ValueError("Vercel lifetime must be between 60 and 86400 seconds")
        if execution_timeout is None:
            execution_timeout = min(900.0, lifetime / 2)
        if (
            type(execution_timeout) not in (int, float)
            or not math.isfinite(execution_timeout)
            or not 0 < execution_timeout < lifetime
        ):
            raise ValueError("Vercel execution timeout must be positive and shorter than the lifetime")
        if type(vcpus) is not int or not 1 <= vcpus <= 8:
            raise ValueError("Vercel vcpus must be an integer from 1 to 8")
        if wheel is not None and not isinstance(wheel, (str, Path)):
            raise ValueError("Vercel wheel must be a path to an Agno wheel")
        self.namespace = namespace
        self.lifetime = lifetime
        self.vcpus = vcpus
        self.wheel = Path(wheel) if wheel is not None else None
        self.options = options
        self.checkpoints = checkpoints
        self.env = dict(env) if env is not None else None
        self.execution_timeout = execution_timeout
        self.retain_checkpoints = _retention(retain_checkpoints)

    async def _current(self, client: Any, physical: str, session_id: str) -> Any:
        """The running session a handle names; a stopped, replaced or missing one is an error."""
        sandbox = await self._read(client, physical)
        session = None if sandbox is None else sandbox.current_session
        if session is None or session.id != session_id or str(session.status) != "running":
            raise _NotSent("Sandbox is not running")
        return session

    async def _stop_session(self, client: Any, physical: str, session_id: str) -> None:
        sandbox = await self._read(client, physical)
        if sandbox is None:
            return
        session = sandbox.current_session
        # Another session of the same sandbox is not this handle's to stop.
        if session is None or session.id != session_id or str(session.status) in _ENDED:
            return
        try:
            await session.stop()
        except Exception as error:
            if _not_found(error):
                return
            raise SandboxError(f"Could not stop the Vercel session: {_describe(error)}") from error
        if str(session.status) not in _ENDED:
            raise SandboxError("Vercel session did not stop")

    @staticmethod
    async def _quietly(operation: Awaitable[None]) -> Optional[Exception]:
        """Finish a cleanup however often the caller is cancelled, and return its failure instead of raising it.

        The operation makes its own client, so the caller's cleanup cannot close one under it. A cancelled
        caller is held until the operation is done (a loop that ends first would cancel it), and the
        cancellation is still what it raises.
        """
        task = asyncio.ensure_future(operation)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            failure = await _drain(task)
            if failure is not None:
                log_warning(f"Vercel cleanup failed while its caller was cancelled: {_describe(failure)}")
            raise
        except Exception as error:
            return error
        return None

    async def _stop_quietly(self, handle: SandboxHandle) -> Optional[Exception]:
        return await self._quietly(self.astop(handle))

    async def astop(self, handle: SandboxHandle) -> None:
        physical, session_id = _bound(handle)
        client = _new_client(self.options)
        try:
            await self._stop_session(client, physical, session_id)
        finally:
            await _close(client)

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

        return VercelCheckpointTransfer(self, store)

    # Identity

    def _prefix(self, session_id: str, agent_id: Optional[str], generation: int) -> str:
        identity = json.dumps([self.namespace, agent_id, session_id, generation])
        return "ag-" + hashlib.sha256(identity.encode()).hexdigest()[:10]

    def _digest(self, session_id: str, agent_id: Optional[str], generation: int, env: Mapping[str, str]) -> str:
        data = {
            "image": IMAGE,
            "python": GUEST_PYTHON,
            "pins": list(NATIVE_PINS),
            "vcpus": self.vcpus,
            "lifetime": self.lifetime,
            "agent_id": agent_id,
            "session_id": session_id,
            "generation": generation,
            "env": dict(env),
            "layout": "vercel-v1",
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _check_environment(env: Mapping[str, str]) -> None:
        for name in env:
            if name in MANAGED_ENVIRONMENT:
                raise ValueError(f"Vercel computers set {name} themselves; it cannot be part of the environment")

    def _tags(self, session_id: str, agent_id: Optional[str], generation: int, digest: str) -> Dict[str, str]:
        return {
            "agno_ns": self.namespace,
            "agno_agent": agent_id or "",
            "agno_session": session_id,
            "agno_gen": str(generation),
            "agno_cfg": digest,
        }

    # Reading

    @staticmethod
    async def _read(client: Any, physical: str) -> Optional[Any]:
        try:
            return await client.get_sandbox(name=physical)
        except Exception as error:
            if _not_found(error):
                return None
            raise SandboxError(f"Could not read the Vercel sandbox: {_describe(error)}") from error

    async def _handle_for(self, sandbox: Any) -> SandboxHandle:
        """The handle for a sandbox, rebuilt from its own tags; a running guest is usable once its marker agrees."""
        tags = sandbox.tags or {}
        if tags.get("agno_ns") not in (None, self.namespace):
            raise SandboxError("Vercel sandbox does not belong to this sandbox namespace")
        if not (tags.get("agno_ns") and tags.get("agno_cfg") and tags.get("agno_session")):
            raise SandboxError("Vercel sandbox has incomplete sandbox identity metadata")
        try:
            generation = int(tags["agno_gen"])
            agent_id = tags["agno_agent"] or None
        except (KeyError, ValueError) as error:
            raise SandboxError("Vercel sandbox has incomplete sandbox identity metadata") from error
        if generation < 1:
            raise SandboxError("Vercel sandbox has incomplete sandbox identity metadata")
        session = sandbox.current_session
        status = str((session.status if session is not None else sandbox.status) or "")
        if status == "running":
            ready = session is not None and await self._ready(session, tags["agno_cfg"])
            state = "running" if ready else "created"
        elif status in _STATES:
            state = _STATES[status]
        else:
            raise SandboxError(f"Vercel sandbox reports an unknown status {status!r}")
        return SandboxHandle(
            provider_ref=sandbox.name,
            name=f"{sandbox.name}/{sandbox.current_session_id}",
            agent_id=agent_id,
            session_id=tags["agno_session"],
            generation=generation,
            state=state,
            config_digest=tags["agno_cfg"],
        )

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        if not isinstance(provider_ref, str) or not provider_ref or "\x00" in provider_ref or "/" in provider_ref:
            raise ValueError("Invalid Vercel sandbox reference")
        client = _new_client(self.options)
        try:
            sandbox = await self._read(client, provider_ref)
            return None if sandbox is None else await self._handle_for(sandbox)
        finally:
            await _close(client)

    # Discovery

    def _accepts(self, sandbox: Any, prefix: str, session_id: str, agent_id: Optional[str], generation: int) -> bool:
        """A listed sandbox is this allocation's only if its name, tags and persistence all say so; a prefix alone proves nothing."""
        tags = sandbox.tags or {}
        return (
            re.fullmatch(re.escape(prefix) + r"-[0-9a-f]{12}", str(sandbox.name)) is not None
            and not getattr(sandbox, "persistent", False)
            and tags.get("agno_ns") == self.namespace
            and tags.get("agno_agent") == (agent_id or "")
            and tags.get("agno_session") == session_id
            and tags.get("agno_gen") == str(generation)
            and bool(tags.get("agno_cfg"))
        )

    async def _listing(self, client: Any, session_id: str, agent_id: Optional[str], generation: int) -> List[Any]:
        """Every sandbox of this allocation, oldest first. All pages are read: a match may be on the last."""
        prefix = self._prefix(session_id, agent_id, generation)
        query = _sdk().SandboxQueryByName(name_prefix=prefix + "-")
        found: List[Any] = []
        seen = 0
        try:
            async for sandbox in client.query_sandboxes(query=query):
                seen += 1
                if seen > _MAX_LISTED:
                    raise SandboxError("Too many Vercel sandboxes share this allocation's name prefix")
                if self._accepts(sandbox, prefix, session_id, agent_id, generation):
                    found.append(sandbox)
                else:
                    log_debug(f"Ignoring Vercel sandbox {sandbox.name!r}: its tags do not match this allocation")
        except SandboxError:
            raise
        except Exception as error:
            raise SandboxError(f"Could not list Vercel sandboxes: {_describe(error)}") from error
        return sorted(found, key=_created_key)

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
        self._check_environment(values)
        digest = self._digest(session_id, agent_id, generation, values)
        client = _new_client(self.options)
        try:
            listed = await self._listing(client, session_id, agent_id, generation)
            if not listed:
                return None
            if len(listed) > 1:
                log_warning(
                    f"{len(listed)} Vercel sandboxes exist for one allocation; reporting the newest, deleting none"
                )
            sandbox = await self._read(client, listed[-1].name)
            if sandbox is None:
                return None
            handle = await self._handle_for(sandbox)
            if handle.config_digest != digest:
                raise SandboxError("Existing generation has different compute configuration")
            return handle
        finally:
            await _close(client)

    # Creation

    def _wheel(self) -> Optional[Path]:
        if self.wheel is None:
            return None
        if self.wheel.suffix != ".whl" or not self.wheel.is_file():
            raise ValueError(f"The Vercel wheel {str(self.wheel)!r} is not an Agno wheel file")
        return self.wheel

    async def acreate(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
    ) -> SandboxHandle:
        values = _identity(session_id, agent_id, generation, env)
        self._check_environment(values)
        wheel = self._wheel()
        digest = self._digest(session_id, agent_id, generation, values)
        client = _new_client(self.options)
        try:
            usable = []
            for sandbox in await self._listing(client, session_id, agent_id, generation):
                if (sandbox.tags or {}).get("agno_cfg") != digest:
                    continue  # another configuration is neither adopted nor deleted
                fresh = await self._read(client, sandbox.name)
                if fresh is None:
                    continue
                handle = await self._handle_for(fresh)
                if handle.state == "running":
                    usable.append(handle)
            if len(usable) > 1:
                raise SandboxError("There is more than one usable Vercel computer for this generation")
            if usable:
                return usable[0]
            return await self._create(client, session_id, agent_id, generation, digest, values, wheel)
        finally:
            await _close(client)

    async def _create(
        self,
        client: Any,
        session_id: str,
        agent_id: Optional[str],
        generation: int,
        digest: str,
        env: Mapping[str, str],
        wheel: Optional[Path],
    ) -> SandboxHandle:
        # Random names keep delayed name-based deletes separate from replacement attempts.
        name = f"{self._prefix(session_id, agent_id, generation)}-{secrets.token_hex(6)}"
        try:
            sandbox = await client.create_sandbox(
                name=name,
                image=IMAGE,
                persistent=False,
                execution_time_limit=self.lifetime,
                resources=_sdk().SandboxResources(vcpus=self.vcpus, memory=_MEMORY_PER_VCPU * self.vcpus),
                tags=self._tags(session_id, agent_id, generation, digest),
            )
        except Exception as error:
            # Do not retry an uncertain create; later discovery may find the orphan.
            raise SandboxError(f"Could not create the Vercel sandbox: {_describe(error)}") from error
        session = sandbox.current_session
        handle = SandboxHandle(
            provider_ref=name,
            name=f"{name}/{sandbox.current_session_id}",
            agent_id=agent_id,
            session_id=session_id,
            generation=generation,
            state="running",
            config_digest=digest,
        )
        try:
            if session is None:
                raise SandboxError("The new Vercel sandbox has no running session")
            await self._bootstrap(session, digest, env, wheel)
        except BaseException as error:
            removal = await self._quietly(self.adestroy(handle))
            if not isinstance(error, Exception):
                if removal is not None:
                    log_warning(
                        f"Could not remove the Vercel sandbox after {type(error).__name__}: {_describe(removal)}"
                    )
                raise
            message = f"Vercel bootstrap failed: {_describe(error)}"
            if removal is not None:
                message += f"; the computer could not be removed either: {_describe(removal)}"
            raise SandboxError(message) from error
        return handle

    async def _guard_call(
        self,
        handle: SandboxHandle,
        command: str,
        name: str,
        *,
        request: Optional[Mapping[str, Any]] = None,
        archive: Optional[Path] = None,
        timeout: float,
    ) -> Dict[str, Any]:
        """Stage what the guard reads, run one guard command as root on the handle's exact session, and return its JSON answer.

        A failure before the command is sent is ``_NotSent``. After that the outcome is the caller's to
        reconcile: nothing here stops the computer or sends the command again.
        """
        physical, session_id = _bound(handle)
        client = _new_client(self.options)
        try:
            try:
                session = await self._current(client, physical, session_id)
                if request is not None:
                    await session.fs.write_bytes(f"{INBOX}/{name}.json", json.dumps(request).encode(), mode=0o600)
                if archive is not None:
                    await self._upload(session, f"{INBOX}/{name}.tar", archive)
            except _NotSent:
                raise
            except Exception as error:
                raise _NotSent(f"Could not stage the {command} request: {_describe(error)}") from error
            stdout, stderr = _Capture(_REPLY_LIMIT, strict=True), _Capture(_STDERR_LIMIT, strict=False)
            try:
                completed = await asyncio.wait_for(
                    session.run_process(
                        PYTHON,
                        ["-I", "-m", "agno.sandbox.vercel.guard", command, name],
                        cwd="/",
                        sudo=True,
                        kill_after=timeout,
                        stdout=stdout,
                        stderr=stderr,
                    ),
                    timeout + _HOST_GRACE,
                )
            except Exception as error:
                if _credentials_failed(error):
                    raise _NotSent(f"Could not resolve Vercel credentials: {_describe(error)}") from error
                raise SandboxError(f"The {command} request failed: {_describe(error)}") from error
            errors = stderr.text()
            if completed.returncode == REFUSED and errors.startswith(REFUSAL_PREFIX):
                refusal = errors[len(REFUSAL_PREFIX) :].strip()
                # The guard's code precedes any text derived from the agent's files.
                if refusal.startswith("content: "):
                    raise CheckpointContentError(
                        f"These files cannot be checkpointed: {refusal.removeprefix('content: ')[:500]}"
                    )
                raise SandboxError(f"Vercel computer refused to {command}: {refusal[-500:]}")
            if completed.returncode:
                raise SandboxError(f"The {command} request failed ({completed.returncode}): {errors[-500:].strip()}")
            try:
                reply = json.loads(stdout.text() or "{}")
            except ValueError as error:
                raise SandboxError(f"The {command} request returned something other than JSON") from error
            if not isinstance(reply, dict):
                raise SandboxError(f"The {command} request returned something other than an object")
            return reply
        finally:
            await _close(client)

    @staticmethod
    async def _upload(session: Any, path: str, source: Path) -> None:
        size = source.stat().st_size
        async with session.fs.open(path, "wb", size=size, permissions=0o600) as writer:
            with source.open("rb") as stream:
                while chunk := await asyncio.to_thread(stream.read, _CHUNK):
                    await writer.write(chunk)

    async def _read_file(self, handle: SandboxHandle, path: str, size: int, destination: Path) -> None:
        """Copy exactly ``size`` bytes of a file in the computer to ``destination``."""
        physical, session_id = _bound(handle)
        client = _new_client(self.options)
        try:
            try:
                session = await self._current(client, physical, session_id)
                async with session.fs.open(path, "rb") as reader:
                    received = 0
                    with destination.open("xb") as output:
                        while received < size:
                            data = await reader.read(min(_CHUNK, size - received))
                            if not data:
                                raise SandboxError("Checkpoint export ended before its reported size")
                            await asyncio.to_thread(output.write, data)
                            received += len(data)
                    if await reader.read(1):
                        raise SandboxError("Checkpoint export changed size while it was read")
            except SandboxError:
                raise
            except Exception as error:
                raise SandboxError(f"Could not download the checkpoint export: {_describe(error)}") from error
        finally:
            await _close(client)

    async def _root(self, session: Any, command: str, args: Sequence[str], timeout: float) -> str:
        """One bounded command as root; its standard output, or an error naming what failed."""
        stdout, stderr = _Capture(MAX_MARKER, strict=False), _Capture(_STDERR_LIMIT, strict=False)
        shown = " ".join([command, *args][:4])
        try:
            completed = await asyncio.wait_for(
                session.run_process(
                    command, list(args), cwd="/", sudo=True, kill_after=timeout, stdout=stdout, stderr=stderr
                ),
                timeout + _HOST_GRACE,
            )
        except asyncio.TimeoutError as error:
            raise SandboxError(f"{shown} did not finish in time") from error
        if completed.returncode:
            raise SandboxError(f"{shown} exited {completed.returncode}: {stderr.text()[-500:].strip()}")
        return stdout.text()

    async def _bootstrap(self, session: Any, digest: str, env: Mapping[str, str], wheel: Optional[Path]) -> None:
        """Install the guest side as root, check it matches this host, and write the marker last of all."""
        await self._root(session, "uv", ["--version"], _QUICK_STEP)
        await self._root(session, "mkdir", ["-p", _BOOTSTRAP], _QUICK_STEP)
        await self._root(
            session, "env", [*_UV_ENVIRONMENT, "uv", "venv", "--python", GUEST_PYTHON, f"{_BOOTSTRAP}/venv"], _VENV_STEP
        )
        if wheel is None:
            import agno

            requirement = f"agno[claude,codex]=={agno.__version__}"
        else:
            staged = f"{_WHEEL_STAGE}/{wheel.name}"
            await session.fs.mkdir(_WHEEL_STAGE)
            await session.fs.write_bytes(staged, wheel.read_bytes(), mode=0o644)
            requirement = f"{staged}[claude,codex]"
        await self._root(
            session,
            "env",
            [*_UV_ENVIRONMENT, "uv", "pip", "install", "--python", PYTHON, requirement, *NATIVE_PINS],
            _INSTALL_STEP,
        )
        # The interpreter and packages are root's to write and the agent's to read.
        await self._root(session, "chmod", ["-R", "go+rX", f"{_BOOTSTRAP}/python", f"{_BOOTSTRAP}/venv"], _VENV_STEP)
        if wheel is not None:
            await self._root(session, "rm", ["-rf", _WHEEL_STAGE], _QUICK_STEP)
        reported = await self._root(session, PYTHON, ["-I", "-m", "agno.sandbox.vercel.guard", "digest"], _VENV_STEP)
        try:
            guest_digest = json.loads(reported)["source_digest"]
        except (ValueError, KeyError, TypeError) as error:
            raise SandboxError("The guest did not report its Agno source digest") from error
        host_digest = _host_digest()
        if guest_digest != host_digest:
            raise SandboxError(
                "The computer's installed Agno source differs from this host's. "
                "Pass wheel= built from this checkout (cd libs/agno && uv build --wheel)"
            )
        await self._root(session, "install", ["-d", "-m", "0700", "-o", str(STAGED_UID), INBOX], _QUICK_STEP)
        request = uuid4().hex
        marker = {
            "config_digest": digest,
            "source_digest": host_digest,
            "route": "release" if wheel is None else "wheel",
            "guest_python": GUEST_PYTHON,
            "pins": list(NATIVE_PINS),
        }
        # The environment travels in the staged request, never in a command line or a tag.
        await session.fs.write_bytes(
            f"{INBOX}/{request}.json", json.dumps({"env": dict(env), "marker": marker}).encode(), mode=0o600
        )
        await self._root(session, PYTHON, ["-I", "-m", "agno.sandbox.vercel.guard", "finish", request], _VENV_STEP)
        if not await self._ready(session, digest):
            raise SandboxError("The computer did not report ready after its bootstrap")

    # Destruction

    async def adestroy(self, handle: SandboxHandle) -> None:
        physical, session_id = _bound(handle)
        client = _new_client(self.options)
        try:
            sandbox = await self._read(client, physical)
            if sandbox is None:
                return
            expected = self._tags(handle.session_id, handle.agent_id, handle.generation, handle.config_digest)
            tags = sandbox.tags or {}
            if (
                any(tags.get(key) != value for key, value in expected.items())
                or str(sandbox.current_session_id) != session_id
            ):
                raise SandboxError(
                    "The Vercel sandbox no longer belongs to this handle; it was neither stopped nor deleted"
                )
            await self._stop_session(client, physical, session_id)
            try:
                await sandbox.destroy()
            except Exception as error:
                if not _not_found(error):
                    raise SandboxError(f"Could not delete the Vercel sandbox: {_describe(error)}") from error
        finally:
            await _close(client)

    async def _ready(self, session: Any, config_digest: str) -> bool:
        """Whether the guard vouches for a marker that agrees with this host's configuration and source; asking never changes the guest."""
        stdout, stderr = _Capture(MAX_MARKER, strict=True), _Capture(_STDERR_LIMIT, strict=False)
        try:
            completed = await asyncio.wait_for(
                session.run_process(
                    PYTHON,
                    ["-I", "-m", "agno.sandbox.vercel.guard", "ready"],
                    cwd="/",
                    sudo=True,
                    kill_after=_READY_SECONDS,
                    stdout=stdout,
                    stderr=stderr,
                ),
                _READY_SECONDS + _HOST_GRACE,
            )
        except Exception as error:
            # A failure to ask is not an answer; it must not read as "not ready" or as "ready".
            raise SandboxError(f"Could not check whether the Vercel guest is ready: {_describe(error)}") from error
        if completed.returncode:
            return False
        try:
            marker = json.loads(stdout.text())
        except ValueError:
            return False
        # A retained computer must still match the host after an upgrade.
        return (
            isinstance(marker, dict)
            and marker.get("config_digest") == config_digest
            and marker.get("source_digest") == _host_digest()
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

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Runtime start/poll over the same guarded command path, leaving compute alone on any failure.

        A control request exits on its own, so a lost reply is for the caller to reconcile; the base
        default would route through ``aexec`` and stop the computer.
        """
        if operation not in ("start", "poll") or not isinstance(payload, bytes) or len(payload) > 1024 * 1024:
            raise ValueError("Runtime RPC requires start/poll and a payload no larger than 1 MiB")
        try:
            wait = float(json.loads(payload).get("wait", 0) or 0)
        except (ValueError, AttributeError):
            wait = 0.0
        if not math.isfinite(wait):
            wait = 0.0
        return await self._aexec(
            handle,
            ["python", "-I", "-m", "agno.sandbox.runtime", operation],
            timeout=_RPC_BASE_SECONDS + min(max(wait, 0.0), 30.0),
            max_output_bytes=4 * 1024 * 1024,
            stdin=payload,
            stop_on_failure=False,
        )

    async def _aexec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float,
        max_output_bytes: int,
        stdin: bytes,
        stop_on_failure: bool = True,
    ) -> ExecResult:
        """Stage the request, run it through the guard once, and read the runner's reply.

        With ``stop_on_failure`` any outcome that leaves a command possibly still running on the
        computer (an error after submission, a cancel, the host deadline, an unreadable reply, the
        runner's own timeout or output limit) stops the exact session. The command is never sent
        twice. Runtime control requests pass False: they exit on their own.
        """
        if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("Commands must be a nonempty sequence of strings")
        if not math.isfinite(timeout) or timeout <= 0 or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("Timeout must be positive and output limit must be between 1 byte and 4 MiB")
        if not isinstance(stdin, bytes) or len(stdin) > 8 * 1024 * 1024:
            raise ValueError("Command stdin must be bytes no larger than 8 MiB")
        physical, session_id = _bound(handle)
        request = json.dumps(
            {
                "argv": list(argv),
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
                "stdin": base64.b64encode(stdin).decode("ascii"),
            }
        ).encode()
        # Checked before anything is sent: the guard applies the same limit and refuses a larger request.
        if len(request) > MAX_STAGED:
            raise ValueError("Command argv and stdin exceed the staged request limit once encoded")
        failure = "Sandbox command transport failed" if stop_on_failure else "Runtime request failed"
        name = uuid4().hex
        # The runner's JSON escapes each byte of output to at most 6 characters and stdout and stderr share
        # max_output_bytes, so this is twice the worst case plus the envelope.
        stdout = _Capture(12 * max_output_bytes + 65536, strict=True)
        stderr = _Capture(_STDERR_LIMIT, strict=False)
        client = _new_client(self.options)
        try:
            session = await self._current(client, physical, session_id)
            # The SDK has no stdin. Stage a one-use request; upload alone never executes it.
            try:
                await session.fs.write_bytes(f"{INBOX}/{name}.json", request, mode=0o600)
            except Exception as error:
                raise SandboxError(f"Could not stage the command request: {_describe(error)}") from error
            try:
                completed = await asyncio.wait_for(
                    session.run_process(
                        PYTHON,
                        ["-I", "-m", "agno.sandbox.vercel.guard", "exec", name],
                        cwd="/",
                        sudo=True,
                        kill_after=timeout + _KILL_GRACE,
                        stdout=stdout,
                        stderr=stderr,
                    ),
                    timeout + _HOST_GRACE,
                )
            except BaseException as error:
                if _credentials_failed(error):  # nothing was sent, so nothing needs stopping
                    raise SandboxError(f"Could not resolve Vercel credentials: {_describe(error)}") from error
                # The command may still be running: a dropped caller does not end remote work.
                stop_error = await self._stop_quietly(handle) if stop_on_failure else None
                if not isinstance(error, Exception):
                    if stop_error is not None:
                        log_warning(
                            f"Could not stop the Vercel session after {type(error).__name__}: {_describe(stop_error)}"
                        )
                    raise
                raise SandboxError(_with_stop_failure(f"{failure}: {_describe(error)}", stop_error)) from error
            code, errors = completed.returncode, stderr.text()
            if code == REFUSED and errors.startswith(REFUSAL_PREFIX):
                # Only the guard exits with this status, so nothing ran and nothing needs stopping.
                raise SandboxError(
                    "Vercel computer refused the command: " + errors[len(REFUSAL_PREFIX) :].strip()[-500:]
                )
            try:
                if code:
                    raise ValueError(errors[-500:] or f"guard exited with {code}")
                result = _result(stdout.text())
            except ValueError as error:
                stop_error = await self._stop_quietly(handle) if stop_on_failure else None
                raise SandboxError(_with_stop_failure(f"{failure}: {str(error)[:500]}", stop_error)) from error
            if stop_on_failure and (result.timed_out or result.output_limited):
                stop_error = await self._stop_quietly(handle)
                if stop_error is not None:
                    raise SandboxError(
                        _with_stop_failure("Sandbox command timed out or exceeded its output limit", stop_error)
                    ) from stop_error
            return result
        finally:
            await _close(client)


def _with_stop_failure(message: str, stop_error: Optional[Exception]) -> str:
    if stop_error is None:
        return message
    return f"{message}; the computer could not be stopped either: {_describe(stop_error)}"
