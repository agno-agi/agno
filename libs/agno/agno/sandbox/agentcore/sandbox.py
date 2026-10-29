"""Amazon Bedrock AgentCore Runtime sandboxes: one runtime session per sandbox generation."""

import asyncio
import base64
import hashlib
import json
import math
import random
import shlex
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Sequence
from uuid import uuid4

from agno.sandbox.agentcore.server import _MAX_STAGED
from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle, _identity, _retention
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer

_GUARD_EXIT = 125
# AgentCore rejects these before anything runs, so a retry cannot repeat work.
# Throttling appears when many sessions start at once: the default quota is 25
# new sessions per second.
_RETRYABLE = ("RetryableConflictException", "ThrottlingException", "ThrottledException")
# Gateway and server errors leave the outcome unknown. Invocations that are safe
# to repeat (claim and start by identity, describe, peek and poll read only, chunks by
# offset) retry them; a command, an export or an import never does.
_SERVER_ERRORS = ("500", "502", "503", "504", "InternalServerException", "ServiceException")
# Refused by AgentCore before a request reaches the computer.
_REJECTED = _RETRYABLE + (
    "AccessDeniedException",
    "ValidationException",
    "ResourceNotFoundException",
    "ServiceQuotaExceededException",
    "UnauthorizedException",
    "InvalidInputException",
)
_ATTEMPTS = 10
_MAX_COMMAND = 64 * 1024
# Commands run for up to an hour and write their result only at the end, so their
# reads wait longer than any command may run.
_COMMAND_READ_TIMEOUT = 3600 + 180


class _Refusal(SandboxError):
    """A refusal by the in-computer server's own checks, carrying its code."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def _error_code(error: BaseException) -> str:
    response = getattr(error, "response", None)
    return response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""


def _not_sent(error: BaseException) -> bool:
    """True when a command request certainly never reached the computer."""
    from botocore.exceptions import (
        ConnectTimeoutError,
        EndpointConnectionError,
        NoCredentialsError,
        ParamValidationError,
    )

    if isinstance(error, (ConnectTimeoutError, EndpointConnectionError, NoCredentialsError, ParamValidationError)):
        return True
    return _error_code(error) in _REJECTED


async def _thread(function: Any, *args: Any, **kwargs: Any) -> Any:
    # A boto3 call cannot be cancelled once sent. Drain it so a cancelled caller
    # never races a retry or cleanup against a request still in flight.
    task = asyncio.ensure_future(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class AgentCoreSandbox(Sandbox):
    """Sandbox compute on a deployed AgentCore Runtime.

    The runtime's image must run ``python -I -m agno.sandbox.agentcore.server serve``
    as its entrypoint. Each generation is the runtime session named after its
    identity, so create is idempotent and a lost create reply is found again by
    name. Every session is a microVM with 2 vCPU and 8 GiB, internet egress in
    PUBLIC mode, and the runtime's IAM role. Code in the sandbox can use that
    role, so give it only the model access the harness needs.

    Each claim carries a random incarnation, kept in ``SandboxHandle.name``, and
    every request names it. A microVM that AgentCore starts after the claimed one
    ended therefore never runs work for an earlier handle: it is either unclaimed,
    which this class stops, or claimed again with a different incarnation.

    Limitation: without durable state outside the microVM, ``create`` cannot tell
    an expired generation from a new one, so after an idle timeout or lifetime it
    claims a fresh, empty microVM for the same generation. Callers that lose a
    computer must recover into a new generation, as with every provider; a
    coordinator that records generations enforces this.

    ``lifetime`` is enforced inside the microVM: at the deadline the computer
    refuses work, ends the agent's processes and exits, so a turn still running
    then dies with it. Set it from the coordinator's own turn budget rather than
    relying on the one-hour default. AgentCore also ends every session at the
    runtime's maxLifetime, which this class cannot read: keep ``lifetime`` at or
    below it, or AgentCore ends the microVM first and every later lookup of that
    generation pays for a replacement microVM and its stop. agentcore_setup.py
    prints the value it gave the runtime.

    Passed as sandbox= on ClaudeAgent or CodexAgent, each turn runs on a new
    generation restored from the last checkpoint. ``execution_timeout`` bounds one
    turn and must be shorter than ``lifetime``, which also has to cover the restore
    before the turn and the capture after it; it defaults to 900 seconds or half
    the lifetime, whichever is shorter. For Claude through Bedrock, set
    ``env={"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": ...}`` and give the
    runtime's role model access.

    Stop and destroy end the microVM. Pause is not supported. Files live on the
    microVM's disk; AgentCore session storage is not used because SQLite cannot
    open a database on it.
    """

    def __init__(
        self,
        runtime_arn: str,
        *,
        namespace: str = "default",
        qualifier: str = "DEFAULT",
        lifetime: int = 3600,
        boto_session: Optional[Any] = None,
        request_timeout: float = 120,
        max_connections: int = 10,
        checkpoints: Optional["CheckpointStore"] = None,
        env: Optional[Mapping[str, str]] = None,
        execution_timeout: Optional[float] = None,
        retain_checkpoints: Optional[int] = 3,
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as error:
            raise ImportError("Install agno[agentcore-sandbox] to use AgentCore sandboxes") from error
        parts = runtime_arn.split(":")
        if len(parts) != 6 or parts[2] != "bedrock-agentcore" or not parts[5].startswith("runtime/"):
            raise ValueError("AgentCore runtime ARN must look like arn:aws:bedrock-agentcore:REGION:ACCOUNT:runtime/ID")
        if not namespace or "\x00" in namespace or type(lifetime) is not int or lifetime < 60:
            raise ValueError("AgentCore namespace must be nonempty and lifetime at least 60 seconds")
        if request_timeout < 60:
            raise ValueError("AgentCore request timeout must cover a 30 second long poll")
        if type(max_connections) is not int or max_connections < 1:
            raise ValueError("AgentCore max_connections must be a positive integer")
        if execution_timeout is None:
            execution_timeout = min(900.0, lifetime / 2)
        if not math.isfinite(execution_timeout) or not 0 < execution_timeout < lifetime:
            raise ValueError("AgentCore execution timeout must be positive and shorter than the lifetime")
        self.checkpoints = checkpoints
        self.env = dict(env) if env is not None else None
        self.execution_timeout = execution_timeout
        self.retain_checkpoints = _retention(retain_checkpoints)
        self.runtime_arn, self.namespace, self.qualifier, self.lifetime = runtime_arn, namespace, qualifier, lifetime
        session = boto_session or boto3.session.Session()

        def client(read_timeout: float) -> Any:
            # An uncertain command must never be sent twice, so the SDK does not
            # retry; _call retries only what AgentCore refused before running.
            # Each session in flight holds a connection, and a long poll holds it
            # for up to 30 seconds. Size the pool to the sessions served at once.
            config = Config(
                region_name=parts[3],
                read_timeout=read_timeout,
                connect_timeout=10,
                retries={"total_max_attempts": 1, "mode": "standard"},
                max_pool_connections=max_connections,
            )
            return session.client("bedrock-agentcore", config=config)

        self._data = client(request_timeout)
        self._commands = client(_COMMAND_READ_TIMEOUT)
        # Sessions this object stopped, with when, oldest first. Calling one again
        # would only start an unclaimed replacement microVM. An entry is dropped once
        # a lifetime has passed: by then the claimed microVM has exited anyway.
        self._stopped: Dict[str, float] = {}
        # A claim retrying through throttling must not land after a stop of the same
        # session; both hold that session's lock for their whole request.
        self._session_locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        from agno.sandbox.agentcore.transfer import AgentCoreCheckpointTransfer

        return AgentCoreCheckpointTransfer(self, store)

    def _name(self, session_id: str, agent_id: Optional[str], generation: int) -> str:
        identity = json.dumps([self.namespace, agent_id, session_id, generation])
        return "agno-" + hashlib.sha256(identity.encode()).hexdigest()[:40]

    def _digest(self, session_id: str, agent_id: Optional[str], generation: int, env: Mapping[str, str]) -> str:
        data = {
            "runtime_arn": self.runtime_arn,
            "qualifier": self.qualifier,
            "lifetime": self.lifetime,
            "agent_id": agent_id,
            "session_id": session_id,
            "generation": generation,
            "env": dict(env),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _call(function: Any, *, idempotent: bool = False, **kwargs: Any) -> Any:
        retryable = _RETRYABLE + _SERVER_ERRORS if idempotent else _RETRYABLE
        for attempt in range(_ATTEMPTS):
            try:
                return function(**kwargs)
            except Exception as error:
                if _error_code(error) not in retryable or attempt == _ATTEMPTS - 1:
                    raise
                log_debug(f"AgentCore {_error_code(error)}, retrying (attempt {attempt + 1} of {_ATTEMPTS})")
                # Full jitter spreads a burst of throttled creates across the window.
                time.sleep(random.uniform(0, min(8.0, 0.5 * 2**attempt)))

    def _invoke(
        self, provider_ref: str, operation: str, /, *, idempotent: bool = True, slow: bool = False, **payload: Any
    ) -> Any:
        body = json.dumps(dict(payload, op=operation)).encode()
        # Export and import may run for up to 14 minutes inside the computer, so they
        # use the client whose reads wait that long.
        client = self._commands if slow else self._data
        response = self._call(
            client.invoke_agent_runtime,
            idempotent=idempotent,
            agentRuntimeArn=self.runtime_arn,
            qualifier=self.qualifier,
            runtimeSessionId=provider_ref,
            payload=body,
            contentType="application/json",
            accept="application/json",
        )
        reply = json.loads(response["response"].read())
        if not isinstance(reply, dict) or not reply.get("ok"):
            reason = reply.get("error", reply) if isinstance(reply, dict) else reply
            message = "AgentCore sandbox refused " + operation + ": " + str(reason)[:1000]
            code = reply.get("code") if isinstance(reply, dict) else None
            if isinstance(code, str):
                raise _Refusal(message, code)
            raise SandboxError(message)
        return reply["value"]

    @staticmethod
    def _expect(handle: SandboxHandle) -> Dict[str, str]:
        return {"config": handle.config_digest, "incarnation": handle.name.rpartition("/")[2]}

    async def _invoke_for(
        self, handle: SandboxHandle, operation: str, /, *, idempotent: bool = True, slow: bool = False, **payload: Any
    ) -> Any:
        """Invoke an operation on the computer a handle names, and no other."""
        if handle.provider_ref in self._stopped:
            log_debug(f"AgentCore sandbox {handle.provider_ref} was stopped here; refusing {operation}")
            raise SandboxError("Sandbox is not running")
        try:
            return await _thread(
                self._invoke,
                handle.provider_ref,
                operation,
                idempotent=idempotent,
                slow=slow,
                expect=self._expect(handle),
                **payload,
            )
        except _Refusal as error:
            if error.code == "unclaimed":
                # This call started a replacement microVM: the claimed one ended.
                await self._stop(handle.provider_ref)
                raise SandboxError("Sandbox is not running; its microVM ended") from error
            raise

    def _handle(self, provider_ref: str, metadata: Mapping[str, str], incarnation: str) -> SandboxHandle:
        if metadata.get("namespace") != self.namespace:
            raise SandboxError("AgentCore computer does not belong to this sandbox namespace")
        try:
            return SandboxHandle(
                provider_ref=provider_ref,
                name=provider_ref + "/" + incarnation,
                agent_id=metadata["agent"] or None,
                session_id=metadata["session"],
                generation=int(metadata["generation"]),
                state="running",
                config_digest=metadata["config"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxError("AgentCore computer has incomplete sandbox identity") from error

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        """The handle for a running computer, or None.

        Not read-only on an ended session. AgentCore cannot inspect a session
        without calling it, and calling an ended one starts a replacement microVM,
        about 12 seconds cold, which this then stops, about 12 seconds more. Only
        sessions this object stopped itself are answered without a call, so another
        replica pays about 25 seconds for each lookup of an ended generation.
        """
        if not provider_ref.startswith("agno-") or len(provider_ref) < 33:
            raise ValueError("Invalid AgentCore sandbox reference")
        if provider_ref in self._stopped:
            return None
        description = await _thread(self._invoke, provider_ref, "describe")
        if not description["claimed"]:
            # This call started a replacement microVM because the claimed one has
            # ended. Release it and report the generation gone.
            await self._stop(provider_ref)
            return None
        return self._handle(provider_ref, description["metadata"], description["incarnation"])

    async def afind(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
        for_create: bool = False,
    ) -> Optional[SandboxHandle]:
        """The claimed computer of a generation, or None if it has none.

        A lookup of a generation with no claimed computer starts a microVM. With
        ``for_create``, this leaves it running, and the create that follows claims it
        instead of waiting for another. Otherwise no create will claim it, so this
        stops it rather than let it idle until the runtime's idle timeout.
        """
        values = _identity(session_id, agent_id, generation, env)
        name = self._name(session_id, agent_id, generation)
        if name in self._stopped:
            return None
        reply = await _thread(self._invoke, name, "peek")
        if not reply["claimed"]:
            # A retired microVM was reached through aget or a stale handle, and no
            # create can claim it.
            if reply["retired"] or not for_create:
                await self._stop(name, record=False)
            return None
        handle = self._handle(name, reply["metadata"], reply["incarnation"])
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
        if name in self._stopped:
            raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
        digest = self._digest(session_id, agent_id, generation, values)
        metadata = {
            "namespace": self.namespace,
            "agent": agent_id or "",
            "session": session_id,
            "generation": str(generation),
            "config": digest,
        }
        try:
            claim = await _thread(self._claim, name, metadata, values)
        except _Refusal as error:
            if error.code == "identity":
                raise SandboxError("Sandbox generation already exists with different configuration") from error
            if error.code == "unusable":
                raise SandboxError("Sandbox generation is not usable; recovery requires a new generation") from error
            raise
        return self._handle(name, metadata, claim["incarnation"])

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Runtime start/poll through InvokeAgentRuntime to the in-computer runtime server.

        A failed or lost reply never touches the claimed computer: the caller
        reconciles. Only an unclaimed replacement microVM is stopped.
        """
        if (
            operation not in ("start", "poll", "resolve", "capabilities")
            or not isinstance(payload, bytes)
            or len(payload) > 1024 * 1024
        ):
            raise ValueError("Runtime RPC requires start/poll/resolve/capabilities and a payload no larger than 1 MiB")
        reply = await self._invoke_for(handle, "rpc", operation=operation, payload=payload.decode())
        body = str(reply["body"])[: 4 * 1024 * 1024]
        if reply["status"] != 200:
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
        if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("Commands must be a nonempty sequence of strings")
        if not math.isfinite(timeout) or timeout <= 0 or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("Timeout must be positive and output limit must be between 1 byte and 4 MiB")
        if timeout > 3500:
            raise ValueError("AgentCore commands run for at most 3500 seconds")
        if not isinstance(stdin, bytes) or len(stdin) > 8 * 1024 * 1024:
            raise ValueError("Command stdin must be bytes no larger than 8 MiB")
        request = json.dumps(
            {
                "argv": list(argv),
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
                "stdin": base64.b64encode(stdin).decode("ascii"),
            }
        ).encode()
        # Checked before anything is sent: the server applies the same limit, and a
        # request it refuses must not cost the computer.
        if len(request) > _MAX_STAGED:
            raise ValueError("Command argv and stdin exceed the 12 MiB staged request limit once encoded")
        # The command API has no stdin, so the runner's request is staged first and
        # handed to the command by the guard, which deletes it.
        name = uuid4().hex
        expect = self._expect(handle)
        command = shlex.join(
            ["python", "-I", "-m", "agno.sandbox.agentcore.server", "exec"]
            + ["--expect", expect["config"] + ":" + expect["incarnation"], "--stdin", name]
        )
        if len(command.encode()) > _MAX_COMMAND:
            raise SandboxError("AgentCore command exceeds 64 KiB")
        # Nothing runs until the command is sent, so a failed upload leaves compute
        # as it is. A staged file whose upload reply was lost is never executed.
        # Staging names the handle's incarnation, so it also refuses a computer the
        # handle does not own, with no separate lookup first.
        await self._invoke_for(handle, "stage", name=name, data=base64.b64encode(request).decode("ascii"))
        try:
            code, out, err, timed_out = await _thread(self._command, handle.provider_ref, command, timeout + 15)
        except BaseException as error:
            if not _not_sent(error):
                # The command may still be running remotely. Stop compute to bound
                # it; recovery belongs to the caller.
                await asyncio.shield(self.astop(handle))
            raise
        if code == _GUARD_EXIT and err.startswith("AgentCore computer refusing to run ["):
            # Code running after the privilege drop could print the same refusal, so
            # trust it only if the guard recorded it where only root can write.
            refusal = await _thread(self._invoke, handle.provider_ref, "refusal", name=name)
            if refusal["refused"]:
                if refusal["code"] == "unclaimed":
                    # The server retired this replacement microVM, so stopping it
                    # cannot hit a computer claimed in the meantime.
                    await self._stop(handle.provider_ref)
                raise SandboxError("AgentCore computer refused the command: " + err.strip()[-500:])
        try:
            if code or timed_out:
                raise ValueError(err[-500:] or "command transport timed out")
            result = ExecResult(**json.loads(out))
        except (TypeError, ValueError) as error:
            await self.astop(handle)
            raise SandboxError("Sandbox command transport failed: " + str(error)[:500]) from error
        if result.timed_out or result.output_limited:
            await self.astop(handle)
        return result

    def _command(self, provider_ref: str, command: str, timeout: float) -> tuple:
        response = self._call(
            self._commands.invoke_agent_runtime_command,
            agentRuntimeArn=self.runtime_arn,
            qualifier=self.qualifier,
            runtimeSessionId=provider_ref,
            contentType="application/json",
            accept="application/vnd.amazon.eventstream",
            body={"command": command, "timeout": min(3600, max(1, math.ceil(timeout)))},
        )
        stdout, stderr, stop = [], [], None
        for event in response["stream"]:
            chunk = event.get("chunk", {})
            if "contentDelta" in chunk:
                stdout.append(chunk["contentDelta"].get("stdout") or "")
                stderr.append(chunk["contentDelta"].get("stderr") or "")
            elif "contentStop" in chunk:
                stop = chunk["contentStop"]
        if stop is None:
            raise SandboxError("AgentCore command stream ended without an exit status")
        return int(stop.get("exitCode", -1)), "".join(stdout), "".join(stderr), stop.get("status") == "TIMED_OUT"

    def _record_stop(self, provider_ref: str) -> None:
        now = time.monotonic()
        self._stopped.pop(provider_ref, None)
        self._stopped[provider_ref] = now
        expired = []
        for name, stopped_at in self._stopped.items():
            if now - stopped_at < self.lifetime:
                break
            expired.append(name)
        with self._locks_guard:
            for name in expired:
                del self._stopped[name]
                lock = self._session_locks.get(name)
                if lock is not None and not lock.locked():
                    del self._session_locks[name]

    def _session_lock(self, provider_ref: str) -> threading.Lock:
        with self._locks_guard:
            return self._session_locks.setdefault(provider_ref, threading.Lock())

    def _claim(self, provider_ref: str, metadata: Mapping[str, str], env: Mapping[str, str]) -> Any:
        with self._session_lock(provider_ref):
            if provider_ref in self._stopped:
                log_debug(f"AgentCore sandbox {provider_ref} was stopped here; refusing claim")
                raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
            return self._invoke(provider_ref, "claim", metadata=dict(metadata), env=dict(env), lifetime=self.lifetime)

    async def _stop(self, provider_ref: str, *, record: bool = True) -> None:
        def stop() -> None:
            with self._session_lock(provider_ref):
                # Recorded first: if the call is cancelled or its reply lost after
                # AgentCore stopped the microVM, this provider must still never
                # revive the generation. A microVM never claimed has no generation
                # to protect, so the next create may start a fresh one.
                if record:
                    self._record_stop(provider_ref)
                log_debug(f"Stopping AgentCore sandbox {provider_ref}" + ("" if record else " (never claimed)"))
                try:
                    self._call(
                        self._data.stop_runtime_session,
                        idempotent=True,
                        agentRuntimeArn=self.runtime_arn,
                        qualifier=self.qualifier,
                        runtimeSessionId=provider_ref,
                    )
                except Exception as error:
                    if _error_code(error) != "ResourceNotFoundException":
                        raise

        # StopRuntimeSession returns once AgentCore has terminated the microVM.
        await _thread(stop)
        if not record:
            # Nothing guards a session that was never claimed, so its lock can go.
            with self._locks_guard:
                lock = self._session_locks.get(provider_ref)
                if lock is not None and not lock.locked() and provider_ref not in self._stopped:
                    del self._session_locks[provider_ref]

    async def astop(self, handle: SandboxHandle) -> None:
        await self._stop(handle.provider_ref)

    async def adestroy(self, handle: SandboxHandle) -> None:
        # A stopped AgentCore session keeps nothing, so destroy and stop are the same.
        await self._stop(handle.provider_ref)
