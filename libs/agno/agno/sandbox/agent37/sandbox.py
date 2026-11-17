"""Agent 37 sandboxes: one instance per sandbox generation, driven through its REST API."""

import asyncio
import base64
import hashlib
import io
import json
import math
import os
import random
import re
import shlex
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    BinaryIO,
    Callable,
    Coroutine,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)
from uuid import uuid4

from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle, _identity, _retention, rpc_wait
from agno.sandbox.pool import LoopClients
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer

_API = "https://api.agent37.com/v1"
_EXEC = "https://sandbox.agent37.app/v1"
_GUEST = (Path(__file__).parent / "_guest.py").read_text()
_RUNNER = (Path(__file__).parent.parent / "_exec.py").read_text()
_METADATA = "agno_"
# Agent 37 reports a sleeping instance, which keeps its memory and wakes on demand; the contract calls that paused.
_STATES = {"sleeping": "paused"}
# Statuses that end in running, stopped or failed without another request.
_SETTLING = ("provisioning", "starting", "waking", "restarting", "updating")
_ATTEMPTS = 5
# Agent 37 holds a command's connection for 15 minutes; the runner ends a command before that.
MAX_COMMAND_SECONDS = 840
# Agent 37 remembers a command's name for 5 minutes after it finishes. A resend this soon after the
# first send therefore always joins that run instead of starting it again.
_REJOIN_SECONDS = 240
# Bytes of staged input per command; with base64 and the script the request stays well under
# Agent 37's 1 MB body limit.
_PUT_CHUNK = 512 * 1024
# Bytes of staged output per command; base64 keeps the reply under Agent 37's 512 KB per stream.
_GET_CHUNK = 256 * 1024
# Chunks in flight at once; an instance runs at most 48 commands at a time.
_PARALLEL = 8
_MAX_RESULT = 32 * 1024 * 1024
_CREATE_SECONDS = 300.0
_WAKE_SECONDS = 240.0
_POLL_SECONDS = 1.0


class _Refused(SandboxError):
    """Agent 37 turned the request down before anything ran, so compute is as it was."""


def _decode(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:1000]


def _problem(data: Any) -> Tuple[str, str]:
    """The code and message of an error body, which is nested from the API and flat from the edge."""
    if not isinstance(data, dict):
        return "", str(data)[:500]
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or ""), str(error.get("message") or "")[:500]
    return str(error or ""), str(data.get("message") or "")[:500]


def _now() -> Tuple[float, float]:
    # Wall time counts a suspended host, which the monotonic clock may not; the larger elapsed reading is the safe one.
    return time.monotonic(), time.time()


def _backoff(attempt: int) -> float:
    return random.uniform(0, min(8.0, 0.5 * 2**attempt))


def _new_client() -> Any:
    import httpx

    limits = httpx.Limits(max_connections=256, max_keepalive_connections=64)
    return httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(15.0, read=60.0))


class Agent37Sandbox(Sandbox):
    """Sandbox compute on Agent 37: each generation is one instance created from ``template``.

    Everything goes through Agent 37's REST API with the workspace key, read from
    ``AGENT37_API_KEY`` when ``api_key`` is not given. Commands run through the exec
    API as root and drop to UID/GID 1000 in /workspace with HOME=/runtime, so any
    template with ``python3`` works; the default ``agent37-base`` needs no setup.

    Passed as sandbox= on ClaudeAgent or CodexAgent, the template must also carry
    this package and the harness SDK: build the cookbook's runtime image for
    linux/amd64 and register it as a template. The runtime is spawned per request
    through exec, so the instance listens on no port.

    Agent 37 takes no idempotency key on create, so an instance is named after its
    generation and a lost reply is resolved by listing the workspace. When two
    creates of one generation overlap, the oldest instance wins and the others are
    deleted. Listing reads every instance in the workspace.

    Pause puts the instance to sleep and resume starts it: memory and processes are
    kept, except that an instance Agent 37 moved to cold storage wakes with its
    files only. Stop halts the instance; its disk stays, and is billed, until
    destroy. Create never restarts a stopped generation.

    An instance bills until it is destroyed and nothing ends one on its own, so
    sweep instances named ``agno-`` that no session owns.

    ``env`` is stored by Agent 37 with the instance and follows its naming rules.
    A command runs for at most 840 seconds.
    """

    def __init__(
        self,
        template: str = "agent37-base",
        *,
        id: Optional[str] = None,
        api_key: Optional[str] = None,
        namespace: str = "default",
        resources: Optional[Mapping[str, int]] = None,
        instance_type: Optional[str] = None,
        region: Optional[str] = None,
        network: Optional[Union[str, Mapping[str, Sequence[str]]]] = None,
        checkpoints: Optional["CheckpointStore"] = None,
        env: Optional[Mapping[str, str]] = None,
        execution_timeout: float = 900,
        retain_checkpoints: Optional[int] = 3,
    ) -> None:
        for value in (template, namespace):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("Agent 37 template and namespace must be nonempty strings")
        key = api_key or os.getenv("AGENT37_API_KEY")
        if not key:
            raise ValueError("Agent 37 needs an API key: pass api_key or set AGENT37_API_KEY")
        if resources is not None and (
            not set(resources) <= {"cpu", "memory", "disk"}
            or any(type(value) is not int or value < 1 for value in resources.values())
        ):
            raise ValueError("Agent 37 resources are positive integers for cpu, memory and disk")
        if not math.isfinite(execution_timeout) or not 0 < execution_timeout <= 86400:
            raise ValueError("Sandbox execution timeout must be between 0 and 86400 seconds")
        if id is not None and (not isinstance(id, str) or not id):
            raise ValueError("Sandbox id must be None or a nonempty string")
        self.id = id
        self.template = template
        self.namespace = namespace
        self.resources = dict(resources) if resources is not None else None
        self.instance_type = instance_type
        self.region = region
        self.network = (
            network if network is None or isinstance(network, str) else {k: list(v) for k, v in network.items()}
        )
        self.checkpoints = checkpoints
        self.env = dict(env) if env is not None else None
        self.execution_timeout = execution_timeout
        self.retain_checkpoints = _retention(retain_checkpoints)
        self._api_key = key
        self._clients = LoopClients(_new_client)

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        from agno.sandbox.agent37.transfer import Agent37CheckpointTransfer

        return Agent37CheckpointTransfer(self, store)

    def _name(self, session_id: str, agent_id: Optional[str], generation: int) -> str:
        identity = json.dumps([self.namespace, agent_id, session_id, generation])
        return "agno-" + hashlib.sha256(identity.encode()).hexdigest()[:40]

    def _options(self) -> Dict[str, Any]:
        """The create fields this sandbox sets, left to Agent 37's defaults when unset."""
        options = {
            "resources": self.resources,
            "type": self.instance_type,
            "region": self.region,
            "network": self.network,
        }
        return {key: value for key, value in options.items() if value is not None}

    def _digest(self, session_id: str, agent_id: Optional[str], generation: int, env: Mapping[str, str]) -> str:
        data = {
            "template": self.template,
            "options": self._options(),
            "agent_id": agent_id,
            "session_id": session_id,
            "generation": generation,
            "env": dict(env),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    async def _api(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        idempotent: bool = True,
        accept: Tuple[int, ...] = (),
        timeout: float = 60.0,
    ) -> Tuple[int, Any]:
        """Call the instances API. Only a request Agent 37 refused, or one safe to repeat, is sent again."""
        import httpx

        headers = {"Authorization": "Bearer " + self._api_key}
        for attempt in range(_ATTEMPTS):
            last = attempt == _ATTEMPTS - 1
            try:
                response = await self._clients.get().request(
                    method, _API + path, json=body, headers=headers, timeout=httpx.Timeout(15.0, read=timeout)
                )
            except httpx.HTTPError as error:
                unsent = isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                if last or not (idempotent or unsent):
                    reason = str(error) or type(error).__name__
                    raise SandboxError(f"Agent 37 request failed: {method} {path}: {reason}") from error
                await asyncio.sleep(_backoff(attempt))
                continue
            data = _decode(response)
            if response.status_code < 300 or response.status_code in accept:
                return response.status_code, data
            code, message = _problem(data)
            # try_again is a refusal: another operation holds the instance for a moment.
            if not last and (code == "try_again" or (idempotent and response.status_code >= 500)):
                log_debug(f"Agent 37 {code or response.status_code} on {method} {path}, retrying")
                await asyncio.sleep(_backoff(attempt))
                continue
            raise SandboxError(f"Agent 37 refused {method} {path}: {code or response.status_code} {message}".strip())
        raise SandboxError(f"Agent 37 request failed: {method} {path}")

    def _handle(self, record: Any) -> SandboxHandle:
        metadata = record.get("metadata") if isinstance(record, dict) else None
        if not isinstance(metadata, dict) or metadata.get(_METADATA + "namespace") != self.namespace:
            raise SandboxError("Instance does not belong to this sandbox namespace")
        try:
            return SandboxHandle(
                provider_ref=record["id"],
                name=record["name"],
                agent_id=metadata[_METADATA + "agent"] or None,
                session_id=metadata[_METADATA + "session"],
                generation=int(metadata[_METADATA + "generation"]),
                state=_STATES.get(record["status"], record["status"]),
                config_digest=metadata[_METADATA + "config"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxError("Instance has incomplete sandbox identity metadata") from error

    async def _delete(self, provider_ref: str) -> None:
        await self._api("DELETE", "/instances/" + provider_ref, accept=(404,))

    async def _resolve(self, name: str) -> Optional[Dict[str, Any]]:
        """The instance that owns a generation's name: the oldest, with any later duplicate deleted."""
        _, listing = await self._api("GET", "/instances")
        records = listing.get("data") if isinstance(listing, dict) else None
        if not isinstance(records, list):
            raise SandboxError("Agent 37 returned an invalid instance listing")
        matches = [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("name") == name
            and (record.get("metadata") or {}).get(_METADATA + "namespace") == self.namespace
            and record.get("status") not in ("deleting", "deleted")
        ]
        matches.sort(key=lambda record: (record.get("created") or 0, str(record.get("id"))))
        for duplicate in matches[1:]:
            # A create whose reply was lost and then repeated. Every creator settles on the oldest.
            log_debug(f"Deleting duplicate Agent 37 instance {duplicate.get('id')} of {name}")
            try:
                await self._delete(str(duplicate.get("id")))
            except SandboxError as error:
                log_debug(f"Could not delete duplicate Agent 37 instance: {error}")
        return matches[0] if matches else None

    async def _settled(
        self, provider_ref: str, seconds: float, pending: Tuple[str, ...] = _SETTLING
    ) -> Optional[SandboxHandle]:
        """The instance once it has left the ``pending`` states, or as it stands when time runs out."""
        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            current = await self.aget(provider_ref)
            if current is None or current.state not in pending:
                return current
            if asyncio.get_running_loop().time() >= deadline:
                return current
            await asyncio.sleep(_POLL_SECONDS)

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

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        if not isinstance(provider_ref, str) or not re.fullmatch(r"[a-z0-9]{1,64}", provider_ref):
            raise ValueError("Invalid Agent 37 sandbox reference")
        status, record = await self._api("GET", "/instances/" + provider_ref, accept=(404,))
        if status == 404 or (isinstance(record, dict) and record.get("status") == "deleted"):
            return None
        return self._handle(record)

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
        record = await self._resolve(self._name(session_id, agent_id, generation))
        if record is None:
            return None
        handle = self._handle(record)
        if handle.config_digest != self._digest(session_id, agent_id, generation, values):
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
        name = self._name(session_id, agent_id, generation)
        digest = self._digest(session_id, agent_id, generation, values)
        record = await self._resolve(name)
        if record is None:
            body: Dict[str, Any] = {
                "template": self.template,
                "name": name,
                "metadata": {
                    _METADATA + "namespace": self.namespace,
                    _METADATA + "agent": agent_id or "",
                    _METADATA + "session": session_id,
                    _METADATA + "generation": str(generation),
                    _METADATA + "config": digest,
                },
                # A sleeping instance is one its owner paused, never one that idled.
                "auto_sleep": False,
                **self._options(),
            }
            if values:
                body["env"] = values
            try:
                _, created = await self._api("POST", "/instances", body=body, idempotent=False, timeout=_CREATE_SECONDS)
            except SandboxError:
                # A lost reply is resolved by the name. A create that failed holds no files, so it is
                # removed rather than left to block this generation.
                record = await self._resolve(name)
                if record is None:
                    raise
                if record.get("status") == "failed":
                    await self._delete(str(record.get("id")))
                    raise
            else:
                # Settle on the oldest instance in case another create of this generation overlapped.
                record = await self._resolve(name) or created
        handle = self._handle(record)
        if handle.config_digest != digest:
            raise SandboxError("Sandbox generation already exists with different configuration")
        if handle.state == "paused":
            # Only the owner knows whether this is a warm pause or a restore that died halfway,
            # so create never revives it: the owner calls resume, anyone else destroys.
            raise SandboxError("Sandbox generation is paused; resume it or destroy it")
        current: Optional[SandboxHandle] = handle
        if handle.state in _SETTLING:
            current = await self._settled(handle.provider_ref, _CREATE_SECONDS)
        if current is None or current.state != "running":
            raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
        return current

    async def _command(self, provider_ref: str, command: str, *, timeout: float) -> Tuple[int, str, str]:
        """Run one shell command as root and return its exit code, stdout and stderr.

        The request carries a name, so sending it again joins the same run rather than
        starting another. ``_Refused`` means the command certainly never started; any
        other failure leaves the outcome unknown.
        """
        import httpx

        body = {"command": command, "user": "root", "name": uuid4().hex}
        url = f"{_EXEC}/instances/{provider_ref}/exec"
        headers = {"X-Agent37-Key": self._api_key}
        started = _now()
        # Whether any attempt so far may have started the command.
        uncertain = False
        reason, failure = "Agent 37 command request failed", None
        for attempt in range(_ATTEMPTS):
            if attempt:
                await asyncio.sleep(_backoff(attempt - 1))
                # Checked right before each resend, whatever delayed it: past the window Agent 37
                # may have forgotten the name and would run the command a second time.
                if uncertain and max(now - then for now, then in zip(_now(), started)) >= _REJOIN_SECONDS:
                    break
            failure = None
            try:
                response = await self._clients.get().post(
                    url, json=body, headers=headers, timeout=httpx.Timeout(15.0, read=timeout + 30)
                )
            except httpx.HTTPError as error:
                reason = "Agent 37 command request failed: " + (str(error) or type(error).__name__)
                unsent = isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                failure = error
            else:
                data = _decode(response)
                if response.status_code == 200 and isinstance(data, dict) and "exit_code" in data:
                    if data.get("truncated"):
                        raise SandboxError("Agent 37 truncated the command output")
                    return int(data["exit_code"]), str(data.get("stdout") or ""), str(data.get("stderr") or "")
                if response.status_code < 300:
                    raise SandboxError("Agent 37 returned an invalid command reply")
                code, message = _problem(data)
                reason = f"Agent 37 refused the command: {code or response.status_code} {message}".strip()
                # Too many commands at once, a host change or a wake that has not finished: nothing started.
                unsent = response.status_code in (409, 503)
                if response.status_code < 500 and not unsent:
                    # A refusal answers this send only; an earlier one whose reply was lost may be running.
                    raise (SandboxError if uncertain else _Refused)(reason)
            uncertain = uncertain or not unsent
        raise (SandboxError if uncertain else _Refused)(reason) from failure

    async def _guest(
        self, provider_ref: str, operation: str, *arguments: str, data: bytes = b"", timeout: float = 15.0
    ) -> Dict[str, Any]:
        """Run one operation of the in-instance script and return its reply.

        The default timeout suits the chunk operations, which finish at once: a request that
        stalls is then sent again soon, and joins the same run.
        """
        command = shlex.join(["python3", "-I", "-c", _GUEST, operation, *arguments])
        if data:
            # The exec API has no stdin, so input rides in a here-document; "_" is not a base64 character.
            command += " <<'AGNO_EOF'\n" + base64.b64encode(data).decode("ascii") + "\nAGNO_EOF"
        code, out, err = await self._command(provider_ref, command, timeout=timeout)
        if code:
            raise SandboxError(f"Agent 37 sandbox {operation} failed: " + (err.strip()[-500:] or f"exit code {code}"))
        try:
            reply = json.loads(out)
        except ValueError as error:
            raise SandboxError(f"Agent 37 sandbox {operation} returned an invalid reply") from error
        if not isinstance(reply, dict):
            raise SandboxError(f"Agent 37 sandbox {operation} returned an invalid reply")
        return reply

    @staticmethod
    async def _spread(jobs: List[Callable[[], Coroutine[Any, Any, None]]]) -> None:
        """Run chunk transfers a few at a time, ending them all at the first failure."""
        limit = asyncio.Semaphore(_PARALLEL)

        async def one(job: Callable[[], Coroutine[Any, Any, None]]) -> None:
            async with limit:
                await job()

        tasks = [asyncio.create_task(one(job)) for job in jobs]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _send(self, provider_ref: str, name: str, source: BinaryIO) -> List[str]:
        """Stage a stream inside the instance and return its size and digest, which the consumer checks."""

        def measure() -> Tuple[int, str]:
            check, size = hashlib.sha256(), 0
            source.seek(0)
            while chunk := source.read(1024 * 1024):
                check.update(chunk)
                size += len(chunk)
            return size, check.hexdigest()

        size, digest = await asyncio.to_thread(measure)

        def chunk_at(offset: int) -> Callable[[], Coroutine[Any, Any, None]]:
            async def put() -> None:
                # No await between seek and read, so chunks in flight never share a position.
                source.seek(offset)
                data = source.read(_PUT_CHUNK)
                await self._guest(provider_ref, "put", name, str(offset), data=data)

            return put

        await self._spread([chunk_at(offset) for offset in range(0, size, _PUT_CHUNK)])
        return [str(size), digest]

    async def _input(self, provider_ref: str, name: str, request: bytes) -> Tuple[List[str], bytes]:
        """Ready an operation's input: small enough, it rides with the command; otherwise it is staged.

        Returns the size and digest arguments of a staged input, and the bytes to send inline.
        Nothing runs until the operation itself is sent, so a failed upload leaves compute as it is.
        """
        if len(request) <= _PUT_CHUNK:
            return [], request
        try:
            return await self._send(provider_ref, name, io.BytesIO(request)), b""
        except BaseException:
            await asyncio.shield(self._discard(provider_ref, name))
            raise

    async def _receive(
        self, provider_ref: str, name: str, reply: Mapping[str, Any], output: BinaryIO, limit: int
    ) -> None:
        """Write a finished operation's output to a seekable stream and check it against its digest."""
        try:
            size, digest, inline = int(reply["size"]), str(reply["sha256"]), reply.get("data")
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxError("Agent 37 sandbox returned an invalid output description") from error
        if size > limit:
            raise SandboxError("Agent 37 sandbox output exceeds its byte limit")

        def decoded(data: Any, length: int) -> bytes:
            try:
                content = base64.b64decode(data, validate=True)
            except (TypeError, ValueError) as error:
                raise SandboxError("Agent 37 sandbox returned output that is not base64") from error
            if len(content) != length:
                raise SandboxError("Agent 37 sandbox output is not the size it reported")
            return content

        if inline is not None:
            output.write(decoded(inline, size))
        else:

            def chunk_at(offset: int) -> Callable[[], Coroutine[Any, Any, None]]:
                async def get() -> None:
                    length = min(_GET_CHUNK, size - offset)
                    chunk = await self._guest(provider_ref, "get", name, str(offset), str(length))
                    data = decoded(chunk.get("data"), length)
                    # No await between seek and write, so chunks in flight never share a position.
                    output.seek(offset)
                    output.write(data)

                return get

            await self._spread([chunk_at(offset) for offset in range(0, size, _GET_CHUNK)])

        def measure() -> Tuple[int, str]:
            check, total = hashlib.sha256(), 0
            output.seek(0)
            while chunk := output.read(1024 * 1024):
                check.update(chunk)
                total += len(chunk)
            return total, check.hexdigest()

        if await asyncio.to_thread(measure) != (size, digest):
            raise SandboxError("Agent 37 sandbox output does not match its digest")

    async def _discard(self, provider_ref: str, name: str) -> None:
        """Best-effort removal of an operation's staged files."""
        try:
            await self._guest(provider_ref, "remove", name)
        except SandboxError as error:
            log_debug(f"Could not remove staged Agent 37 files: {error}")

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Runtime start/poll through exec. A failed or lost reply leaves compute as it is: the caller reconciles."""
        wait = rpc_wait(operation, payload)
        return await self._aexec(
            handle,
            ["python3", "-I", "-m", "agno.sandbox.runtime", operation],
            timeout=15 + wait,
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
        """Run a command. With ``stop_on_failure`` an unknown outcome stops the instance, since a
        dropped request does not end the remote command; runtime control requests pass False."""
        if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("Commands must be a nonempty sequence of strings")
        if not math.isfinite(timeout) or timeout <= 0 or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("Timeout must be positive and output limit must be between 1 byte and 4 MiB")
        if timeout > MAX_COMMAND_SECONDS:
            raise ValueError("Agent 37 commands run for at most 840 seconds")
        if not isinstance(stdin, bytes) or len(stdin) > 8 * 1024 * 1024:
            raise ValueError("Command stdin must be bytes no larger than 8 MiB")
        current = await self._owned(handle)
        if current is not None and current.state == "paused":
            # The exec API would wake it; only the owner that paused it may.
            raise SandboxError("Sandbox is paused; resume it before running commands")
        if current is None or current.state != "running":
            raise SandboxError("Sandbox is not running")
        request = json.dumps(
            {
                "argv": list(argv),
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
                "stdin": base64.b64encode(stdin).decode("ascii"),
            }
        ).encode()
        ref, name = handle.provider_ref, uuid4().hex
        staged, inline = await self._input(ref, name, request)
        output = io.BytesIO()
        try:
            reply = await self._guest(ref, "run", name, _RUNNER, *staged, data=inline, timeout=timeout + 15)
            try:
                await self._receive(ref, name, reply, output, _MAX_RESULT)
            finally:
                if reply.get("data") is None:
                    await asyncio.shield(self._discard(ref, name))
        except (asyncio.CancelledError, SandboxError) as error:
            # The command may still be running remotely. Stop compute to bound it; recovery
            # belongs to the caller.
            if stop_on_failure and not isinstance(error, _Refused):
                await asyncio.shield(self.astop(handle))
            raise
        try:
            result = ExecResult(**json.loads(output.getvalue()))
        except (TypeError, ValueError) as error:
            if stop_on_failure:
                await self.astop(handle)
            raise SandboxError("Sandbox returned an invalid command result") from error
        if stop_on_failure and (result.timed_out or result.output_limited):
            await self.astop(handle)
        return result

    async def apause(self, handle: SandboxHandle) -> None:
        current = await self._owned(handle)
        if current is not None and current.state == "paused":
            return
        if current is None or current.state != "running":
            raise SandboxError("Only a running sandbox can be paused")
        await self._api("POST", f"/instances/{handle.provider_ref}/sleep", timeout=120)

    async def aresume(self, handle: SandboxHandle) -> SandboxHandle:
        current = await self._owned(handle)
        if current is not None and current.state == "running":
            return current
        if current is None or current.state != "paused":
            raise SandboxError("Sandbox is not paused; recovery requires a new generation")
        # A 202 means the instance is moving hosts: it may still read as asleep, then as starting.
        await self._api("POST", f"/instances/{handle.provider_ref}/start", timeout=120)
        current = await self._settled(handle.provider_ref, _WAKE_SECONDS, _SETTLING + ("paused",))
        if current is None or current.state != "running":
            raise SandboxError("Agent 37 did not bring the sandbox back to running")
        return current

    async def astop(self, handle: SandboxHandle) -> None:
        current = await self._owned(handle)
        if current is None or current.state in ("stopped", "stopping", "failed", "deleting"):
            return
        await self._api("POST", f"/instances/{handle.provider_ref}/stop", accept=(404,), timeout=120)

    async def adestroy(self, handle: SandboxHandle) -> None:
        if await self._owned(handle) is not None:
            await self._delete(handle.provider_ref)
