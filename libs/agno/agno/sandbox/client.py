"""Reconnectable control-plane client for the sandbox execution journal."""

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Mapping, Optional

from agno.sandbox.base import Sandbox, SandboxError, SandboxHandle, _sync

# Seconds a poll is held open inside the container when nothing has happened yet.
_DEFAULT_WAIT = 10.0


@dataclass(frozen=True)
class RuntimeExecution:
    computer: SandboxHandle
    execution_id: str
    run_id: str


@dataclass(frozen=True)
class RuntimePage:
    cursor: int
    events: List[Dict[str, Any]]
    result: Optional[Dict[str, Any]]


class SandboxRuntimeClient:
    """The provider transports requests; no DB/queue credentials enter compute.

    A lost start response is reconciled using the same execution identity and
    identical request. Polling can detach/reconnect without restarting execution.
    A runtime result is execution output, never permission to acknowledge durable
    completion. The coordinator must separately commit a recovery checkpoint.
    """

    def __init__(self, provider: Sandbox) -> None:
        self.provider = provider

    async def _rpc(self, computer: SandboxHandle, operation: str, request: Mapping[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(dict(request), allow_nan=False).encode()
        if len(payload) > 1024 * 1024:
            raise ValueError("Runtime request exceeds 1 MiB")
        task = asyncio.create_task(self.provider.arpc(computer, operation, payload))
        try:
            output = await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancelling the caller's poll must not kill the ongoing SDK worker.
            # Drain the short RPC; explicit cancel stops the session computer.
            await task
            raise
        if output.exit_code or output.timed_out or output.output_limited:
            reason = output.stderr[-2000:] or ("timed out" if output.timed_out else "no reply")
            raise SandboxError("Runtime RPC failed: " + reason)
        try:
            response = json.loads(output.stdout)
        except ValueError as error:
            raise SandboxError("Runtime returned invalid JSON") from error
        if not isinstance(response, dict) or type(response.get("version")) is not int or response["version"] != 1:
            raise SandboxError("Runtime protocol version mismatch")
        if response.get("execution_id") != request.get("execution_id"):
            raise SandboxError("Runtime execution identity mismatch")
        return response

    async def astart(
        self,
        computer: SandboxHandle,
        *,
        execution_id: str,
        run_id: str,
        sdk: str,
        input: str,
        config: Optional[Mapping[str, Any]] = None,
        user_id: Optional[str] = None,
        execution_timeout: float = 900,
        native_session_id: Optional[str] = None,
        media: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeExecution:
        """Start a turn. ``native_session_id`` is the harness's own conversation id the caller
        committed for this session, Claude's session id or Codex's thread id, when it has one:
        the runtime refuses to run, without calling the model, unless the sandbox holds exactly
        that conversation. Leave it None for a session's first turn."""
        response = await self._rpc(
            computer,
            "start",
            {
                "version": 1,
                "execution_id": execution_id,
                "run_id": run_id,
                "agent_id": computer.agent_id,
                "session_id": computer.session_id,
                "sdk": sdk,
                "input": input,
                "config": dict(config or {}),
                "user_id": user_id,
                "execution_timeout": execution_timeout,
                "native_session_id": native_session_id,
                **({"media": media} if media else {}),
                **({"metadata": metadata} if metadata is not None else {}),
            },
        )
        if response.get("accepted") is not True:
            raise SandboxError("Runtime did not acknowledge execution")
        return RuntimeExecution(computer, execution_id, run_id)

    def start(
        self,
        computer: SandboxHandle,
        *,
        execution_id: str,
        run_id: str,
        sdk: str,
        input: str,
        config: Optional[Mapping[str, Any]] = None,
        user_id: Optional[str] = None,
        execution_timeout: float = 900,
        native_session_id: Optional[str] = None,
        media: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuntimeExecution:
        return _sync(
            self.astart(
                computer,
                execution_id=execution_id,
                run_id=run_id,
                sdk=sdk,
                input=input,
                config=config,
                user_id=user_id,
                execution_timeout=execution_timeout,
                native_session_id=native_session_id,
                media=media,
                **({"metadata": metadata} if metadata is not None else {}),
            )
        )

    async def apoll(self, execution: RuntimeExecution, *, cursor: int = 0, wait: float = 0.0) -> RuntimePage:
        """One page from the journal. ``wait`` long-polls inside the container for up to that
        many seconds, returning as soon as there is something to read."""
        if type(cursor) is not int or cursor < 0:
            raise ValueError("Runtime cursor must be a nonnegative integer")
        if not isinstance(wait, (int, float)) or not math.isfinite(wait) or wait < 0:
            raise ValueError("Runtime poll wait must be a nonnegative number")
        request: Dict[str, Any] = {"execution_id": execution.execution_id, "cursor": cursor}
        if wait:
            request["wait"] = min(float(wait), 30.0)
        response = await self._rpc(execution.computer, "poll", request)
        next_cursor, frames, result = response.get("cursor"), response.get("frames"), response.get("result")
        if type(next_cursor) is not int or next_cursor < cursor or not isinstance(frames, list):
            raise SandboxError("Runtime returned an invalid journal page")
        events = []
        for frame in frames:
            if not isinstance(frame, dict) or frame.get("type") != "event" or not isinstance(frame.get("event"), dict):
                raise SandboxError("Runtime returned an invalid event frame")
            event = frame["event"]
            for key, expected in (
                ("run_id", execution.run_id),
                ("session_id", execution.computer.session_id),
                ("agent_id", execution.computer.agent_id),
            ):
                if event.get(key) is not None and event[key] != expected:
                    raise SandboxError("Runtime event identity mismatch")
            if event.get("event") in ("RunCompleted", "RunError", "RunCancelled"):
                raise SandboxError("Runtime must not publish terminal service events")
            events.append(event)
        if result is not None:
            if not isinstance(result, dict) or result.get("type") not in (
                "execution_finished",
                "execution_error",
                "execution_unknown",
            ):
                raise SandboxError("Runtime returned an invalid execution result")
            if result["type"] == "execution_finished":
                run, session = result.get("run"), result.get("session")
                if not isinstance(run, dict) or not isinstance(session, dict):
                    raise SandboxError("Runtime result is missing run/session state")
                if (run.get("run_id"), run.get("session_id"), run.get("agent_id"), session.get("session_id")) != (
                    execution.run_id,
                    execution.computer.session_id,
                    execution.computer.agent_id,
                    execution.computer.session_id,
                ):
                    raise SandboxError("Runtime result identity mismatch")
        return RuntimePage(next_cursor, events, result)

    def poll(self, execution: RuntimeExecution, *, cursor: int = 0, wait: float = 0.0) -> RuntimePage:
        return _sync(self.apoll(execution, cursor=cursor, wait=wait))

    async def await_result(
        self,
        execution: RuntimeExecution,
        *,
        timeout: float = 900,
        poll_interval: float = 0.25,
        wait: float = _DEFAULT_WAIT,
    ) -> Dict[str, Any]:
        """Wait without changing execution lifetime. Timeout detaches; cancel is explicit."""
        async for page in self.apages(execution, timeout=timeout, poll_interval=poll_interval, wait=wait):
            if page.result is not None:
                return page.result
        raise SandboxError("Runtime ended without a result")

    def wait_result(
        self,
        execution: RuntimeExecution,
        *,
        timeout: float = 900,
        poll_interval: float = 0.25,
        wait: float = _DEFAULT_WAIT,
    ) -> Dict[str, Any]:
        return _sync(self.await_result(execution, timeout=timeout, poll_interval=poll_interval, wait=wait))

    async def apages(
        self,
        execution: RuntimeExecution,
        *,
        cursor: int = 0,
        timeout: float = 900,
        poll_interval: float = 0.25,
        wait: float = _DEFAULT_WAIT,
    ) -> AsyncIterator[RuntimePage]:
        """Pages until the result. With ``wait`` the container holds each poll until there is
        news, so an idle turn costs one request per ``wait`` seconds and events arrive as they
        are journaled; ``wait=0`` falls back to sleeping ``poll_interval`` between requests."""
        if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("Runtime polling timeouts must be positive")
        if not math.isfinite(wait) or wait < 0:
            raise ValueError("Runtime poll wait must be a nonnegative number")
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            page = await self.apoll(
                execution, cursor=cursor, wait=min(wait, max(0, deadline - asyncio.get_running_loop().time()))
            )
            cursor = page.cursor
            yield page
            if page.result is not None:
                return
            if not wait:
                await asyncio.sleep(min(poll_interval, max(0, deadline - asyncio.get_running_loop().time())))
        raise TimeoutError("Detached from runtime after wait timeout; execution may still be running")

    def pages(
        self,
        execution: RuntimeExecution,
        *,
        cursor: int = 0,
        timeout: float = 900,
        poll_interval: float = 0.25,
        wait: float = _DEFAULT_WAIT,
    ) -> Iterator[RuntimePage]:
        # Reuse the tested sync poll transport; no hidden background execution.
        import time

        if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("Runtime polling timeouts must be positive")
        if not math.isfinite(wait) or wait < 0:
            raise ValueError("Runtime poll wait must be a nonnegative number")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            page = self.poll(execution, cursor=cursor, wait=min(wait, max(0, deadline - time.monotonic())))
            cursor = page.cursor
            yield page
            if page.result is not None:
                return
            if not wait:
                time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        raise TimeoutError("Detached from runtime after wait timeout; execution may still be running")

    async def acancel(self, execution: RuntimeExecution) -> None:
        """Stop the session computer, including SDK/local tools/background children."""
        await self.provider.astop(execution.computer)

    def cancel(self, execution: RuntimeExecution) -> None:
        _sync(self.acancel(execution))
