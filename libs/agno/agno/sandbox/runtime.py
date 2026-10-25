"""Linux runtime protocol. Execute in the sandbox image, never on an AgentOS API host.

The compute provider authenticates transport. This process has no control-plane
credentials. Its journal reports execution finished, not durable run completion.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from agno.sandbox.base import SandboxError
from agno.sandbox.protocol import NATIVE_SESSION_KEYS
from agno.sandbox.protocol import validate_request as _validate

_VERSION = 1
# The bearer token the host must present to this container's server. The server reads it
# once and drops it from its environment; workers are spawned without it.
_TOKEN_ENV = "AGNO_SANDBOX_RUNTIME_TOKEN"
_MAX_REQUEST = 1024 * 1024
_MAX_FRAME = 256 * 1024
_MAX_RESULT = 1024 * 1024
_MAX_JOURNAL = 16 * 1024 * 1024
_TERMINAL_EVENTS = {"RunCompleted", "RunError", "RunCancelled"}


def _encode(value: Any) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode()


def _atomic(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _job(root: Path, execution_id: str) -> Path:
    if not isinstance(execution_id, str) or not execution_id or len(execution_id) > 256:
        raise ValueError("Invalid runtime execution identity")
    return root / "jobs" / hashlib.sha256(execution_id.encode()).hexdigest()


class NativeStateMissing(SandboxError):
    """The sandbox does not hold the native conversation the caller expects. The model never
    ran; the caller treats this as a failed restore, not a failed turn."""


def _check_native_session_id(agent: Any, request: Dict[str, Any]) -> None:
    """Refuse to run when the caller expects an existing native conversation and the local
    database does not record exactly that one. This is the only check that catches a lost
    database: with no session row the adapter would treat the turn as a new conversation."""
    expected = request.get("native_session_id")
    if expected is None:
        return
    session = agent.get_session(request["session_id"], user_id=request.get("user_id"))
    found = (session.session_data or {}).get(NATIVE_SESSION_KEYS[request["sdk"]]) if session is not None else None
    _require_native(expected, found)


def _require_native(expected: str, found: Optional[str]) -> None:
    if found != expected:
        raise NativeStateMissing(
            "Sandbox native state does not match the session: expected "
            + ("the native conversation " + expected)
            + (", found " + found if found else ", found none")
        )


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SandboxError("Runtime session already has a writer") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _process_start(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (FileNotFoundError, IndexError):
        return None


def _start(root: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    _validate(request)
    if _process_start(os.getpid()) is None:
        raise SandboxError("Sandbox runtime requires Linux process identity tracking")
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    directory = _job(root, request["execution_id"])
    payload = _encode(request)
    with _lock(root / "dispatch.lock"):
        identity_path = root / "identity.json"
        identity = _encode({key: request[key] for key in ("agent_id", "session_id")})
        if identity_path.exists() and identity_path.read_bytes() != identity:
            raise SandboxError("A runtime computer belongs to exactly one agent/session")
        if not identity_path.exists():
            _atomic(identity_path, identity)
        if directory.exists():
            if (directory / "request.json").read_bytes() != payload:
                raise SandboxError("Execution identity already exists with different input")
            return {"version": _VERSION, "execution_id": request["execution_id"], "accepted": True}
        directory.mkdir(mode=0o700)
        _atomic(directory / "request.json", payload)
        _atomic(directory / "status.json", _encode({"phase": "starting", "created_at": time.time()}))
        try:
            subprocess.Popen(
                [sys.executable, "-I", "-m", "agno.sandbox.runtime", "worker", str(directory)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                env=_worker_env(),
            )
        except Exception as error:
            _atomic(directory / "result.json", _encode({"type": "execution_error", "error": str(error)}))
            raise
    return {"version": _VERSION, "execution_id": request["execution_id"], "accepted": True}


def _worker_env() -> Dict[str, str]:
    """The worker's environment: everything the container has, minus the control token."""
    return {key: value for key, value in os.environ.items() if key != _TOKEN_ENV}


def _append(directory: Path, event: Dict[str, Any]) -> None:
    payload = _encode({"type": "event", "event": event}) + b"\n"
    if len(payload) > _MAX_FRAME:
        raise SandboxError("Runtime event exceeds its frame limit")
    path = directory / "events.jsonl"
    with path.open("ab") as stream:
        if stream.tell() + len(payload) > _MAX_JOURNAL:
            raise SandboxError("Runtime event journal exceeds its limit")
        stream.write(payload)
        stream.flush()


async def _fixture(directory: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    # A stand-in native conversation: its id lives in the checkpointed native root, like an SDK's.
    native = directory.parent.parent / "native"
    native.mkdir(exist_ok=True)
    marker = native / "fixture-session"
    found = marker.read_text() if marker.exists() else None
    if request.get("native_session_id") is not None:
        _require_native(request["native_session_id"], found)
    if found is None:
        found = hashlib.sha256(request["session_id"].encode() + os.urandom(16)).hexdigest()[:32]
        marker.write_text(found)
    workspace = Path(os.environ.get("AGNO_SANDBOX_WORKSPACE", "/workspace"))
    workspace.mkdir(exist_ok=True)
    if request.get("media"):
        from agno.agents._media import stage_media
        from agno.sandbox.media import decode_media

        stage_media(workspace, request["run_id"], decode_media(request["media"]))
    with (workspace / "fixture-effects.txt").open("a") as stream:
        stream.write(request["run_id"] + "\n")
    # What the agent's tools would see: the names of our own variables in this environment.
    (workspace / "fixture-env.txt").write_text("\n".join(sorted(k for k in os.environ if k.startswith("AGNO_SANDBOX"))))
    config = request.get("config", {})
    delay, steps = float(config.get("delay", 0)), int(config.get("steps", 1))
    identity = {"run_id": request["run_id"], "session_id": request["session_id"], "agent_id": request["agent_id"]}
    # With steps, the turn streams: one event per step spaced over the delay, then the final
    # content. With the default of one step it is a single event after the delay.
    for step in range(1, steps):
        await asyncio.sleep(delay / steps)
        _append(directory, {"event": "RunContent", "content": f"step {step} of {steps}", **identity})
    await asyncio.sleep(delay / steps)
    _append(directory, {"event": "RunContent", "content": request["input"], **identity})
    return {
        "type": "execution_finished",
        "run": {
            "run_id": request["run_id"],
            "session_id": request["session_id"],
            "agent_id": request["agent_id"],
            "user_id": request.get("user_id"),
            "status": "COMPLETED",
            "content": request["input"],
        },
        "session": {
            "session_id": request["session_id"],
            "user_id": request.get("user_id"),
            "session_data": {"fixture": True, NATIVE_SESSION_KEYS["fixture"]: found},
        },
    }


def _agent(request: Dict[str, Any], native: Path) -> Any:
    from agno.db.sqlite import SqliteDb

    # This local database is native runtime state, not the authoritative service
    # database. It has no network credentials and is checkpointed after SDK drain.
    db = SqliteDb(db_file=str(native / "history.db"))
    config = dict(request.get("config", {}))
    repository = config.pop("repository", None)
    config.update(
        id=request["agent_id"],
        cwd="/workspace/repository" if repository else "/workspace",
        db=db,
        retries=0,
        keep_uploads=True,
        require_native_resume=True,
        strict_persistence=True,
        store_events=True,
    )
    if request["sdk"] == "claude":
        from agno.agents.claude import ClaudeAgent

        return ClaudeAgent(**config)
    from agno.agents.codex import CodexAgent

    return CodexAgent(**config)


async def _prepare_codex(native: Path) -> None:
    # The Codex CLI refuses to start when CODEX_HOME names a missing directory.
    home = native / "codex"
    if home.is_symlink() or (home.exists() and not home.is_dir()):
        raise SandboxError("CODEX_HOME must be a directory; remove the file at native/codex")
    home.mkdir(exist_ok=True)


def _codex_login_needed(native: Path, api_key: str) -> bool:
    """Whether Codex needs logging in with the configured key.

    The Codex app server reads a stored login, not OPENAI_API_KEY. Checkpoints never
    contain auth.json, so a restored computer always logs in. A stored ChatGPT login
    is the user's choice and is kept; a stored API key different from the configured
    one, or an unreadable file, is replaced.
    """
    try:
        stored = json.loads((native / "codex" / "auth.json").read_text())
    except (OSError, ValueError):
        return True
    if not isinstance(stored, dict):
        return True
    if stored.get("tokens"):
        return False
    return stored.get("OPENAI_API_KEY") != api_key


async def _login_codex(agent: Any, api_key: str) -> None:
    """Log Codex in with the configured key."""
    try:
        await agent.alogin_api_key(api_key)
    except Exception as error:
        # The run error is journaled, so it must never carry the key.
        message = str(error).replace(api_key, "[redacted]")
        raise SandboxError("Codex login failed: " + message[:500]) from None


async def _execute(directory: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    from agno.sandbox.repository import RepositoryPreparationError, _aprepare, _read_pin, validate_repository_override

    native = directory.parent.parent / "native"
    repository = request.get("config", {}).get("repository")
    override = validate_repository_override(request.get("metadata"), repository)
    if (native / "repository.json").exists() and repository is None:
        raise ValueError("Continue this session with its pinned repository; set agent.repository")
    if repository is not None:
        try:
            await _aprepare(
                repository,
                Path(os.environ.get("AGNO_SANDBOX_WORKSPACE", "/workspace")),
                native,
                resume=request.get("native_session_id") is not None,
                override=override,
            )
        except asyncio.CancelledError:
            # Preparation drains its filesystem work before cancellation propagates. No
            # harness has started, so the worker's execution deadline is safe to retry.
            raise RepositoryPreparationError("Repository preparation interrupted before model execution") from None
    result = await _execute_harness(directory, request)
    if repository is not None:
        result["repository"] = _read_pin(native, repository)
    return result


async def _execute_harness(directory: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    if request["sdk"] == "fixture":
        return await _fixture(directory, request)
    from agno.run.agent import RunOutput
    from agno.sandbox.media import decode_media

    native = directory.parent.parent / "native"
    native.mkdir(exist_ok=True)
    os.environ["HOME"] = str(native)
    os.environ["CODEX_HOME"] = str(native / "codex")
    if request["sdk"] == "codex":
        await _prepare_codex(native)

    agent = _agent(request, native)
    run = None
    try:
        # Before anything reaches the model: the state on disk must be the state the caller
        # restored. A mismatch is a restore problem and is reported as one.
        _check_native_session_id(agent, request)
        api_key = os.environ.get("OPENAI_API_KEY")
        if request["sdk"] == "codex" and api_key and _codex_login_needed(native, api_key):
            await _login_codex(agent, api_key)
        async for event in agent.arun(
            request["input"],
            run_id=request["run_id"],
            session_id=request["session_id"],
            user_id=request.get("user_id"),
            stream=True,
            stream_events=True,
            yield_run_output=True,
            **decode_media(request.get("media", [])),
        ):
            if isinstance(event, RunOutput):
                run = event
            elif event.event not in _TERMINAL_EVENTS:
                _append(directory, event.to_dict())
        if run is None:
            raise SandboxError("SDK runtime did not produce an execution result")
        session = agent.get_session(request["session_id"], user_id=request.get("user_id"))
        if session is None:
            raise SandboxError("SDK runtime did not retain native session metadata")
        persisted = agent.db.get_run(request["run_id"])
        if (
            persisted is None
            or RunOutput.from_dict(persisted.to_dict()).to_dict() != RunOutput.from_dict(run.to_dict()).to_dict()
        ):
            raise SandboxError("SDK runtime did not durably retain its exact execution result")
        return {"type": "execution_finished", "run": run.to_dict(), "session": session.to_dict(include_runs=False)}
    finally:
        agent.db.db_engine.dispose()


def _worker(directory: Path) -> None:
    request = json.loads((directory / "request.json").read_bytes())
    root = directory.parent.parent
    try:
        _validate(request)
        with _lock(root / "execution.lock"):
            _atomic(
                directory / "status.json",
                _encode({"phase": "running", "pid": os.getpid(), "start": _process_start(os.getpid())}),
            )

            async def bounded_execute() -> Dict[str, Any]:
                return await asyncio.wait_for(_execute(directory, request), request.get("execution_timeout", 900))

            result = asyncio.run(bounded_execute())
            payload = _encode(result)
            if len(payload) > _MAX_RESULT:
                raise SandboxError("Runtime execution result exceeds its limit")
            _atomic(directory / "result.json", payload)
    except Exception as error:
        result = {"type": "execution_error", "error": (str(error) or type(error).__name__)[:2000]}
        from agno.sandbox.repository import RepositoryPreparationError

        if isinstance(error, RepositoryPreparationError):
            result["reason"] = "repository_preparation_failed"
        if isinstance(error, NativeStateMissing):
            # Machine-readable, so a coordinator retries the restore instead of the turn.
            result["reason"] = "native_state_missing"
        _atomic(directory / "result.json", _encode(result))


def _poll(root: Path, execution_id: str, cursor: int) -> Dict[str, Any]:
    if type(cursor) is not int or cursor < 0:
        raise ValueError("Runtime cursor must be a nonnegative integer")
    directory = _job(root, execution_id)
    request = json.loads((directory / "request.json").read_bytes())
    if request["execution_id"] != execution_id:
        raise SandboxError("Runtime execution identity mismatch")
    # Snapshot the immutable finish marker before reading events. If completion
    # races this poll, the next poll drains its final events before exposing it.
    result_path = directory / "result.json"
    result_ready = result_path.exists()
    frames = []
    path = directory / "events.jsonl"
    if path.exists():
        with path.open("rb") as stream:
            if cursor > os.fstat(stream.fileno()).st_size:
                raise ValueError("Runtime cursor exceeds journal length")
            stream.seek(cursor)
            while stream.tell() - cursor < _MAX_FRAME:
                start = stream.tell()
                line = stream.readline(_MAX_FRAME + 1)
                if not line:
                    break
                if len(line) > _MAX_FRAME:
                    raise SandboxError("Runtime event exceeds its frame limit")
                if not line.endswith(b"\n"):
                    stream.seek(start)
                    break
                frames.append(json.loads(line))
            cursor = stream.tell()
            drained = not stream.read(1)
    else:
        if cursor:
            raise ValueError("Runtime journal has no such cursor")
        drained = True
    result = None
    if drained and result_ready:
        if result_path.stat().st_size > _MAX_RESULT:
            raise SandboxError("Runtime execution result exceeds its limit")
        result = json.loads(result_path.read_bytes())
    status = json.loads((directory / "status.json").read_bytes())
    if not result_path.exists():
        if status["phase"] == "running" and _process_start(status["pid"]) != status.get("start"):
            result = {
                "type": "execution_unknown",
                "error": "Runtime worker disappeared; reconcile effects before retrying",
            }
        elif status["phase"] == "starting" and time.time() - status["created_at"] > 30:
            result = {"type": "execution_unknown", "error": "Runtime dispatch outcome is unknown"}
    return {"version": _VERSION, "execution_id": execution_id, "cursor": cursor, "frames": frames, "result": result}


_MAX_WAIT = 30.0


def _poll_wait(root: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    """Poll, holding the request open until there is something to return.

    ``wait`` seconds of long-polling inside the container replaces a tight loop of
    requests from the host: the reply goes out as soon as new journal bytes or the
    result exist, and an idle page costs one request per ``wait`` instead of many.
    """
    wait = request.get("wait", 0)
    if not isinstance(wait, (int, float)) or not math.isfinite(wait) or wait < 0:
        raise ValueError("Runtime poll wait must be a nonnegative number of seconds")
    deadline = time.monotonic() + min(float(wait), _MAX_WAIT)
    while True:
        page = _poll(root, request["execution_id"], request["cursor"])
        if page["frames"] or page["result"] is not None or time.monotonic() >= deadline:
            return page
        time.sleep(0.05)


def _serve(root: Path, port: int, token: Optional[str] = None) -> Any:
    """The runtime as a small HTTP server, run as the container's entrypoint.

    POST /start and POST /poll take the same JSON as the stdin operations and return
    the same JSON; GET /health answers once the server is up. The journal, locks and
    worker are unchanged: this only replaces a process spawn per request with a
    pooled connection, which is what keeps the Docker daemon out of the hot path.

    With a token, every request must carry it as a bearer credential. The provider
    generates one per container and hands it to the coordinator with the handle, so
    a port reachable beyond the host's loopback (a shared daemon, a hosted provider)
    answers only its owner. The agent inside the container can already write the
    journal, so the server grants it nothing new either way.
    """
    import hmac
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    expected = ("Bearer " + token).encode() if token else None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # Headers and body go out as two small writes; without TCP_NODELAY the second waits on
        # the peer's delayed ACK, which turns a millisecond poll into a forty millisecond one.
        disable_nagle_algorithm = True

        def log_message(self, *args: Any) -> None:
            return

        def _authorized(self) -> bool:
            if expected is None:
                return True
            presented = (self.headers.get("Authorization") or "").encode()
            if hmac.compare_digest(presented, expected):
                return True
            self._reply(401, {"error": "Runtime request is missing or carries the wrong token"})
            return False

        def _reply(self, status: int, body: Dict[str, Any]) -> None:
            payload = _encode(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if not self._authorized():
                return
            if self.path == "/health":
                self._reply(200, {"version": _VERSION, "ok": True})
            else:
                self._reply(404, {"error": "Unknown runtime operation"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if self.path not in ("/start", "/poll"):
                self._reply(404, {"error": "Unknown runtime operation"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > _MAX_REQUEST:
                self._reply(413, {"error": "Runtime request exceeds its limit"})
                return
            try:
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("Runtime request must be a JSON object")
                result = _start(root, request) if self.path == "/start" else _poll_wait(root, request)
            except (ValueError, KeyError, TypeError) as error:
                self._reply(400, {"error": str(error) or type(error).__name__})
            except SandboxError as error:
                self._reply(409, {"error": str(error)})
            except Exception as error:
                self._reply(500, {"error": (str(error) or type(error).__name__)[:2000]})
            else:
                self._reply(200, result)

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def server_bind(self) -> None:
            # The stdlib resolves the bind address's FQDN here, a reverse DNS lookup that can
            # stall for seconds in a container with no resolver. The name is never used.
            import socketserver

            socketserver.TCPServer.server_bind(self)
            self.server_name = "sandbox-runtime"
            self.server_port = self.server_address[1]

    return Server(("0.0.0.0", port), Handler)


def _supervise(port: int) -> None:
    """Keep the runtime server alive as a child; the container's main process.

    The server is the least important process in the container and the turn's worker the
    most. If the server were the main process, its crash would stop the container and kill
    the turn. As a child of this loop it is restarted with backoff, workers are untouched
    (they run detached, reparented to init), and the host sees a short gap that the
    cursor-based reconnect absorbs. SIGTERM, which Docker sends on stop, ends the server
    and this loop; Docker then ends whatever else is running.
    """
    import signal

    stopping = False
    child: Optional[subprocess.Popen[bytes]] = None

    def stop(signum: int, frame: Any) -> None:
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # The token is handed to the server on stdin, not in its environment, so the serving
    # process never carries it in /proc/<pid>/environ. This process's own exec-time
    # environment still shows it, as does PID 1's; only a separate UID hides those.
    token = os.environ.pop(_TOKEN_ENV, None) or None
    argv = [sys.executable, "-I", "-m", "agno.sandbox.runtime", "serve", "--port", str(port)]
    if token is not None:
        argv.append("--token-stdin")
    delay = 0.2
    while not stopping:
        started = time.monotonic()
        child = subprocess.Popen(
            argv, stdin=subprocess.PIPE if token is not None else subprocess.DEVNULL, env=dict(os.environ)
        )
        if token is not None and child.stdin is not None:
            with suppress(BrokenPipeError, OSError):
                child.stdin.write((token + "\n").encode())
                child.stdin.close()
        code = child.wait()
        if stopping:
            break
        # A server that ran for a while gets a fresh backoff; a crash loop backs off up to 5 s.
        delay = 0.2 if time.monotonic() - started > 10 else min(delay * 2, 5.0)
        print(f"sandbox runtime server exited with {code}; restarting in {delay:.1f}s", file=sys.stderr, flush=True)
        time.sleep(delay)


def _take_token(from_stdin: bool = False) -> Optional[str]:
    """Read the control token: one line on stdin when the supervisor hands it over, otherwise
    the environment, which is then cleared so nothing spawned later inherits it. Never the
    command line, which is visible in ps."""
    if from_stdin:
        token = sys.stdin.readline().strip() or None
    else:
        token = os.environ.pop(_TOKEN_ENV, None) or None
    if token is None:
        # Acceptable only when the port is unreachable beyond the host's loopback.
        print("sandbox runtime server has no token: every reachable caller is accepted", file=sys.stderr, flush=True)
    return token


def main() -> None:
    parser = argparse.ArgumentParser(description="Sandbox runtime protocol")
    parser.add_argument("operation", choices=("start", "poll", "worker", "serve", "supervise"))
    parser.add_argument("directory", nargs="?")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AGNO_SANDBOX_RUNTIME_PORT", "8765")))
    parser.add_argument("--token-stdin", action="store_true", help="read the control token from the first stdin line")
    args = parser.parse_args()
    root = Path(os.environ.get("AGNO_SANDBOX_RUNTIME_DIR", "/runtime"))
    if args.operation == "worker":
        _worker(Path(args.directory))
        return
    if args.operation == "supervise":
        _supervise(args.port)
        return
    if args.operation == "serve":
        _serve(root, args.port, _take_token(from_stdin=args.token_stdin)).serve_forever()
        return
    request = json.loads(sys.stdin.buffer.read(_MAX_REQUEST + 1))
    result = _start(root, request) if args.operation == "start" else _poll_wait(root, request)
    print(_encode(result).decode())


if __name__ == "__main__":
    main()
