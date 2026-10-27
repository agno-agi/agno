"""In-computer entrypoint for an Amazon Bedrock AgentCore Runtime sandbox image.

``serve`` is the container entrypoint and runs as root. It answers the AgentCore
HTTP contract on port 8080: GET /ping and POST /invocations. An invocation can
claim this microVM for one sandbox generation, describe the claim, forward a
runtime start or poll to the local runtime server, stage command input, or move
a checkpoint in or out.

``exec`` wraps every provider command. It refuses unusable compute, applies the
claimed environment and drops to UID/GID 1000 in /workspace, the same user and
directory the Docker sandbox uses.

Trust boundary. Agent code runs as UID 1000 and can reach this server over
loopback, so the server refuses any connection whose socket belongs to that UID;
AgentCore's own forwarder connects as another user. This assumes nothing in the
image relays loopback traffic to port 8080 as another user. Checkpoint capture and
restore run in a child process dropped to UID 1000, and the host validates every
archive that comes out. The one agent-controlled data root reads is the runtime's
job directory for ``/ping``, walked without following links and capped in size;
agent code can keep a session reporting busy, which its lifetime still bounds.

AgentCore starts a new microVM whenever a stopped session is called again, so a
session id alone never proves which computer answers. The claim lives on this
microVM's own disk and dies with it, and carries a random incarnation that every
later request must name. An unclaimed microVM, or one claimed again after its
predecessor ended, therefore never runs work for an older handle.
"""

import base64
import ctypes
import fcntl
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_CONTROL = Path("/var/lib/agno-control")
_CLAIM = _CONTROL / "claim.json"
_WORKSPACE, _RUNTIME = Path("/workspace"), Path("/runtime")
_PORT = 8080
_RUNTIME_PORT = 8765
_TOKEN_ENV = "AGNO_SANDBOX_RUNTIME_TOKEN"
_GUARD_EXIT = 125
# A staged runner request: up to 8 MiB of command stdin, which grows by a third
# as base64, plus argv. The provider checks the same limit before it sends.
_MAX_STAGED = 12 * 1024 * 1024
# An invocation body carries a staged request or a checkpoint chunk as base64.
_MAX_BODY = 24 * 1024 * 1024
_MAX_CHUNK = 8 * 1024 * 1024
_MAX_TRANSFER = 2 * 1024 * 1024 * 1024
# The interpreter command line for processes this server starts.
_PYTHON = [sys.executable, "-I"]
_USER = 1000
_GROUP = 1000
_ROOTS = {"workspace": _WORKSPACE, "native": _RUNTIME / "native"}
# Lifecycle markers, root-only like the claim. "used" is set once a command or a
# runtime turn starts, "restoring" while an import runs, "capturing" while an export
# has the agent's processes stopped, and "failed" after an import or lifetime
# failure, which refuses all further work.
_USED, _RESTORING, _CAPTURING, _FAILED = "used", "restoring", "capturing", "failed"
# Set while a first claim starts the runtime, so the microVM is not mistaken for
# an unclaimed replacement and retired in the meantime.
_CLAIMING = "claiming"
# Capture and restore children must finish inside one AgentCore invocation,
# which is limited to 15 minutes.
_CHILD_TIMEOUT = 840
_MAX_REPLY = 4 * 1024 * 1024

_lock = threading.Lock()
_state: Dict[str, Any] = {"token": None, "supervisor": None, "timer": None, "unhealthy": 0, "importing": False}
_ping = {"status": "Healthy", "since": int(time.time())}


# Control directory, claim and lifecycle


class _Refused(PermissionError):
    """A refusal by this server's own checks, which the provider acts on by its code.

    The code travels in a separate reply field, so text from the runtime server or
    any other agent-reachable source can never be mistaken for one.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _control_dir() -> None:
    if os.geteuid() != 0:
        raise PermissionError("The AgentCore sandbox server must run as root")
    _CONTROL.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = _CONTROL.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("The control directory must belong to root alone")


def _write_private(path: Path, data: bytes) -> None:
    # A name per writer: the guard and server threads may write the same marker at once.
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _load_claim() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_CLAIM.read_text())
    except FileNotFoundError:
        return None


def _marked(name: str) -> bool:
    return (_CONTROL / name).exists()


def _mark(name: str) -> None:
    _write_private(_CONTROL / name, b"1")


@contextmanager
def _lifecycle() -> Iterator[None]:
    """Serialise lifecycle changes across this server and the command guard.

    The guard is a separate process, so a thread lock cannot cover it. Checking a
    marker and setting another must be one step, or a command could start after a
    restore checked that the generation was unused.
    """
    descriptor = os.open(_CONTROL / "lifecycle.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _usable(claim: Optional[Dict[str, Any]], *, restoring: bool = False) -> Dict[str, Any]:
    """The claim, if this computer may still do work; otherwise raise."""
    if claim is None:
        raise _Refused("unclaimed", "Unclaimed computer")
    if _marked(_FAILED):
        raise _Refused("unusable", "This computer failed a restore or reached its lifetime and must be replaced")
    if time.time() >= claim["deadline"]:
        raise _Refused("unusable", "This computer reached its lifetime and must be replaced")
    if _marked(_RESTORING) and not restoring:
        raise _Refused("busy", "A restore is in progress on this computer")
    return claim


def _begin_work(claim: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Mark the generation used before a command or runtime turn, atomically with the checks."""
    with _lifecycle():
        claim = _usable(claim)
        if _marked(_CAPTURING):
            raise _Refused("busy", "A checkpoint capture is in progress on this computer")
        _mark(_USED)
    return claim


def _sweeper() -> None:
    while True:
        time.sleep(600)
        try:
            _sweep()
        except OSError:
            pass


def _sweep() -> None:
    """Delete staged inputs and transfer objects abandoned for over an hour."""
    cutoff = time.time() - 3600
    for path in _CONTROL.iterdir():
        if path.suffix in (".stdin", ".checkpoint", ".refused"):
            try:
                if path.lstat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                pass


def _retire_if_unclaimed() -> Optional[Dict[str, Any]]:
    """The claim; or, on an unclaimed microVM, retire it so it can never be claimed.

    A request that names a handle can only reach an unclaimed microVM when the
    claimed one ended and AgentCore started a replacement. The provider stops that
    replacement; retiring it first means a create racing that stop cannot claim
    it and then be stopped.
    """
    with _lifecycle():
        claim = _load_claim()
        if claim is None:
            if _marked(_CLAIMING):
                raise _Refused("busy", "A claim is in progress on this computer")
            _mark(_FAILED)
        return claim


def _require(request: Dict[str, Any], *, restoring: bool = False) -> Dict[str, Any]:
    """The claim, if the request names this computer's generation and incarnation."""
    claim = _usable(_retire_if_unclaimed(), restoring=restoring)
    expected = {"config": claim["metadata"].get("config"), "incarnation": claim["incarnation"]}
    if request.get("expect") != expected:
        raise _Refused("identity", "Computer identity mismatch: this is not the computer the handle names")
    return claim


def _drop_privileges() -> None:
    os.setgroups([])
    os.setgid(_GROUP)
    os.setuid(_USER)
    _no_new_privileges()


def _no_new_privileges() -> None:
    # PR_SET_NO_NEW_PRIVS: setuid binaries cannot take a process back to root.
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not disable privilege elevation")


def _as_agent(argv: List[str], **kwargs: Any) -> "subprocess.Popen[bytes]":
    """Start a process as UID 1000 without a pre-exec hook in this threaded server."""
    # Dropping supplementary groups needs root; an unprivileged caller has none to drop.
    extra_groups: Optional[List[int]] = [] if os.geteuid() == 0 else None
    return subprocess.Popen(argv, user=_USER, group=_GROUP, extra_groups=extra_groups, start_new_session=True, **kwargs)


def _environment(claim: Dict[str, Any], **extra: str) -> Dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key != _TOKEN_ENV}
    environment.update(claim["env"])
    environment.update(HOME=str(_RUNTIME), **extra)
    return environment


def _agent_pids() -> List[int]:
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == _USER:
                pids.append(int(entry.name))
        except FileNotFoundError:
            continue
    return pids


def _expire(deadline: float) -> None:
    # AgentCore lifetimes are runtime-wide. At the claimed deadline this computer
    # refuses further work, ends the agent's processes and exits the entrypoint,
    # after which AgentCore marks the microVM unhealthy and ends it.
    time.sleep(max(0.0, deadline - time.time()))
    try:
        _mark(_FAILED)
    except OSError:
        # A full disk must not keep the agent running past its lifetime.
        pass
    for _ in range(3):
        for pid in _agent_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    os._exit(0)


def _start_timer(deadline: float) -> None:
    timer = _state["timer"]
    if timer is None or not timer.is_alive():
        _state["timer"] = threading.Thread(target=_expire, args=(deadline,), daemon=True)
        _state["timer"].start()


# Runtime server


def _start_runtime(claim: Dict[str, Any]) -> None:
    token = secrets.token_urlsafe(32)
    environment = _environment(claim, **{_TOKEN_ENV: token})
    _state["supervisor"] = _as_agent(
        [*_PYTHON, "-m", "agno.sandbox.runtime", "supervise", "--port", str(_RUNTIME_PORT)],
        cwd=_WORKSPACE,
        env=environment,
        stdin=subprocess.DEVNULL,
    )
    _state["token"] = token
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _runtime_healthy():
            _state["unhealthy"] = 0
            return
        time.sleep(0.1)
    raise RuntimeError("The sandbox runtime server did not become ready")


def _runtime_healthy() -> bool:
    if _state["token"] is None:
        return False
    try:
        status, _ = _forward("GET", "/health", None, timeout=2)
    except Exception:
        return False
    return status == 200


def _stop_runtime() -> None:
    """Kill the runtime supervisor and everything in its process group."""
    supervisor, _state["supervisor"], _state["token"] = _state["supervisor"], None, None
    if supervisor is None:
        return
    try:
        os.killpg(supervisor.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    supervisor.wait()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


# The runtime port can be taken over by agent code, so its answers are never
# followed elsewhere, never sent through a proxy, and read only up to a bound.
_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _forward(method: str, path: str, body: Optional[bytes], *, timeout: float) -> Any:
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + str(_state["token"])}
    request = urllib.request.Request(
        f"http://127.0.0.1:{_RUNTIME_PORT}{path}", data=body, headers=headers, method=method
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, data = response.status, response.read(_MAX_REPLY + 1)
    except urllib.error.HTTPError as error:
        status, data = error.code, error.read(_MAX_REPLY + 1)
    if len(data) > _MAX_REPLY:
        raise ValueError("Runtime server reply exceeds its limit")
    return status, data.decode(errors="replace")


# Operations


def _claim(request: Dict[str, Any]) -> Dict[str, Any]:
    metadata, env, lifetime = request.get("metadata"), request.get("env"), request.get("lifetime")
    if not isinstance(metadata, dict) or not all(isinstance(v, str) for v in metadata.values()):
        raise ValueError("Claim metadata must map strings to strings")
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError("Claim environment must map strings to strings")
    if _TOKEN_ENV in env:
        raise ValueError("The runtime token is generated per computer; do not set it in env")
    if type(lifetime) is not int or lifetime < 60:
        raise ValueError("Claim lifetime must be at least 60 seconds")
    _control_dir()
    existing = _load_claim()
    if existing is not None:
        # A claim never changes once written, so a repeat create needs no lock and is
        # answered even while a capture or restore holds the server's lock.
        return _reclaim(existing, metadata, env)
    with _lock:
        existing = _load_claim()
        if existing is not None:
            return _reclaim(existing, metadata, env)
        with _lifecycle():
            if _marked(_FAILED):
                raise _Refused("unusable", "This microVM replaced an ended one and was retired; it must be replaced")
            _mark(_CLAIMING)
        try:
            return _first_claim(metadata, env, lifetime)
        finally:
            (_CONTROL / _CLAIMING).unlink(missing_ok=True)


def _reclaim(existing: Dict[str, Any], metadata: Dict[str, str], env: Dict[str, str]) -> Dict[str, Any]:
    if existing["metadata"] != metadata or existing["env"] != env:
        raise _Refused("identity", "This computer is already claimed with a different identity")
    with _lifecycle():
        if _marked(_RESTORING) and not _state["importing"]:
            # A restore was interrupted: the computer may hold part of a checkpoint.
            _mark(_FAILED)
    _usable(existing, restoring=True)
    # A matching claim only means this computer is ours; repeat create must still hand
    # back a working runtime. A slow health answer under load is not a dead runtime,
    # so restart only after repeated misses, and never while a capture or restore has
    # the runtime stopped on purpose.
    if not (_marked(_CAPTURING) or _marked(_RESTORING)):
        if _runtime_healthy():
            _state["unhealthy"] = 0
        else:
            _state["unhealthy"] += 1
            if _state["unhealthy"] >= 3 and _lock.acquire(blocking=False):
                try:
                    _stop_runtime()
                    try:
                        _start_runtime(existing)
                    except BaseException:
                        _stop_runtime()
                        raise
                finally:
                    _lock.release()
    _start_timer(existing["deadline"])
    return {"metadata": existing["metadata"], "incarnation": existing["incarnation"], "created": False}


def _first_claim(metadata: Dict[str, str], env: Dict[str, str], lifetime: int) -> Dict[str, Any]:
    for path in (_WORKSPACE, _RUNTIME):
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, _USER, _GROUP)
        path.chmod(0o700)
    claim: Dict[str, Any] = {
        "metadata": metadata,
        "env": env,
        "deadline": time.time() + lifetime,
        "incarnation": secrets.token_hex(16),
    }
    # The claim file is the computer's proof of ownership, and the guard runs
    # commands only after it exists. Write it only once the runtime is healthy, so
    # a failed start leaves the computer unclaimed for a retry.
    try:
        _start_runtime(claim)
    except BaseException:
        _stop_runtime()
        raise
    _write_private(_CLAIM, json.dumps(claim).encode())
    _start_timer(claim["deadline"])
    return {"metadata": metadata, "incarnation": claim["incarnation"], "created": True}


def _describe(request: Dict[str, Any]) -> Dict[str, Any]:
    claim = _retire_if_unclaimed()
    if claim is None:
        return {"claimed": False}
    return {"claimed": True, "metadata": claim["metadata"], "incarnation": claim["incarnation"]}


def _peek(request: Dict[str, Any]) -> Dict[str, Any]:
    """The claim, leaving an unclaimed microVM claimable.

    A lookup by identity reaches a fresh microVM whenever the generation was never
    created, and the create that follows claims that same microVM.
    """
    claim = _load_claim()
    if claim is None:
        return {"claimed": False, "retired": _marked(_FAILED)}
    return {"claimed": True, "metadata": claim["metadata"], "incarnation": claim["incarnation"]}


def _rpc(request: Dict[str, Any]) -> Dict[str, Any]:
    claim = _require(request)
    if _state["token"] is None:
        raise _Refused("busy", "The runtime server is not running")
    operation, payload = request.get("operation"), request.get("payload")
    if operation not in ("start", "poll") or not isinstance(payload, str):
        raise ValueError("Runtime RPC requires start/poll and a JSON payload")
    try:
        wait = float(json.loads(payload).get("wait", 0) or 0)
    except (ValueError, AttributeError):
        wait = 0.0
    if operation == "start":
        _begin_work(claim)
    elif _marked(_CAPTURING):
        # The runtime server is stopped with the agent's other processes; answer now
        # rather than hold the poll until it times out.
        raise _Refused("busy", "A checkpoint capture is in progress on this computer")
    status, body = _forward("POST", "/" + operation, payload.encode(), timeout=15 + min(max(wait, 0.0), 30.0))
    return {"status": status, "body": body}


def _stage(request: Dict[str, Any]) -> Dict[str, Any]:
    """Store command input that ``exec --stdin NAME`` hands to the command and deletes."""
    _require(request)
    name = request.get("name", "")
    if not re.fullmatch(r"[a-f0-9]{32}", name):
        raise ValueError("Invalid staged input name")
    data = base64.b64decode(request.get("data", ""), validate=True)
    if len(data) > _MAX_STAGED:
        raise ValueError("Staged input exceeds its limit")
    _sweep()
    _write_private(_CONTROL / (name + ".stdin"), data)
    return {"size": len(data)}


def _transfer_file(name: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", str(name)):
        raise ValueError("Invalid checkpoint transfer object")
    return _CONTROL / (name + ".checkpoint")


def _freeze() -> List[int]:
    """Stop every UID 1000 process until a full pass finds no new one.

    There is no microVM pause; this stands in for Docker's cgroup freeze so files
    hold still while they are archived or restored. It is for consistency only:
    the archive work itself runs as UID 1000, so a process that escapes the freeze
    can at most disturb its own checkpoint. The caller resumes them with ``_thaw``.
    """
    stopped: List[int] = []
    seen: set = set()
    for _ in range(20):
        found = [pid for pid in _agent_pids() if pid not in seen]
        if not found:
            break
        for pid in found:
            seen.add(pid)
            if _process_state(pid) in ("T", "t"):
                # Already stopped by the agent itself; thaw must not resume it.
                continue
            try:
                os.kill(pid, signal.SIGSTOP)
                stopped.append(pid)
            except ProcessLookupError:
                pass
    return stopped


def _process_state(pid: int) -> str:
    try:
        # The state follows the command name, which may itself contain spaces and ")".
        return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return ""


def _thaw(stopped: List[int]) -> None:
    for pid in stopped:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass


def _roots() -> Dict[str, str]:
    return {name: str(path) for name, path in _ROOTS.items()}


def _export(request: Dict[str, Any]) -> Dict[str, Any]:
    """Capture /workspace and /runtime/native into one checkpoint archive.

    A UID 1000 child runs the shared ``CheckpointArchive.capture``, which applies
    the exclusions, including hardlinks to excluded files, and the limits. Its
    output goes straight into a root-only file; the host validates it again.

    The freeze also stops the runtime server, which runs as UID 1000, so host polls
    fail until the export finishes. Docker's pause does the same and the client's
    cursor reconnect absorbs it, so a failed poll here does not mean a lost turn.
    """
    _require(request)
    target = _transfer_file(request["name"])
    job = json.dumps(
        {"roots": _roots(), "state": request["state"], "exclude": request["exclude"], "limits": request["limits"]}
    ).encode()
    _sweep()
    with _lock:
        stopped: List[int] = []
        try:
            with _lifecycle():
                _usable(_load_claim())
                # Commands and runtime turns refuse while this is set, rather than
                # hang on processes the capture has stopped.
                _mark(_CAPTURING)
            stopped = _freeze()
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                child = _as_agent(
                    [*_PYTHON, "-m", "agno.sandbox.agentcore.server", "checkpoint-capture"],
                    stdin=subprocess.PIPE,
                    stdout=descriptor,
                    stderr=subprocess.PIPE,
                    cwd="/",
                )
                _, error = _finish(child, job)
            finally:
                os.close(descriptor)
            if child.returncode:
                raise ValueError("Checkpoint capture failed: " + error.decode(errors="replace")[-1500:])
            size = target.stat().st_size
            if size > _MAX_TRANSFER:
                raise ValueError("Checkpoint capture exceeds the transfer limit")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            _thaw(stopped)
            (_CONTROL / _CAPTURING).unlink(missing_ok=True)
    return {"size": size}


def _finish(child: "subprocess.Popen[bytes]", job: Optional[bytes]) -> Tuple[bytes, bytes]:
    try:
        return child.communicate(job, timeout=_CHILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise ValueError("Checkpoint transfer did not finish within its time limit") from None


def _get(request: Dict[str, Any]) -> Dict[str, Any]:
    _require(request)
    offset, length = request.get("offset"), request.get("length")
    if type(offset) is not int or offset < 0 or type(length) is not int or not 0 < length <= _MAX_CHUNK:
        raise ValueError("Checkpoint reads need a nonnegative offset and a length of at most 8 MiB")
    descriptor = os.open(_transfer_file(request["name"]), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        stream.seek(offset)
        data = stream.read(length)
    return {"data": base64.b64encode(data).decode()}


def _put(request: Dict[str, Any]) -> Dict[str, Any]:
    _require(request)
    path = _transfer_file(request["name"])
    data = base64.b64decode(request["data"], validate=True)
    offset = request.get("offset")
    if type(offset) is not int or offset < 0 or len(data) > _MAX_CHUNK or offset + len(data) > _MAX_TRANSFER:
        raise ValueError("Checkpoint chunks need a nonnegative offset, at most 8 MiB and 2 GiB in total")
    if offset == 0 and not path.exists():
        _sweep()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    else:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r+b") as stream:
        size = os.fstat(stream.fileno()).st_size
        if offset + len(data) <= size:
            # A retried chunk that already landed: accept it only if it matches.
            stream.seek(offset)
            if stream.read(len(data)) != data:
                raise ValueError("Checkpoint chunk conflicts with bytes already written")
        elif offset == size:
            stream.seek(offset)
            stream.write(data)
        else:
            raise ValueError("Checkpoint chunks must arrive in order")
        return {"size": max(size, offset + len(data))}


def _import(request: Dict[str, Any]) -> Dict[str, Any]:
    """Restore a checkpoint into this generation, which must be claimed and unused.

    A UID 1000 child validates and materialises the archive with the shared
    ``CheckpointArchive.restore`` and moves it into the empty managed roots. Any
    failure marks the computer failed, so it refuses all further work.
    """
    _require(request, restoring=True)
    source = _transfer_file(request["name"])
    job = json.dumps({"roots": _roots(), "limits": request["limits"]})
    with _lock:
        with _lifecycle():
            if _marked(_USED) or _marked(_RESTORING) or _marked(_CAPTURING):
                source.unlink(missing_ok=True)
                raise ValueError("Restore requires an empty, unused generation")
            _mark(_RESTORING)
            # Set under the same lock: a repeated claim treats a restoring marker
            # without a running import as an interrupted restore and fails the computer.
            _state["importing"] = True
        stopped: List[int] = []
        try:
            stopped = _freeze()
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                child = _as_agent(
                    [*_PYTHON, "-m", "agno.sandbox.agentcore.server", "checkpoint-restore", job],
                    stdin=descriptor,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd="/",
                )
                output, error = _finish(child, None)
            finally:
                os.close(descriptor)
            if child.returncode:
                raise ValueError("Checkpoint restore failed: " + error.decode(errors="replace")[-1500:])
            state = json.loads(output)
            with _lifecycle():
                _mark(_USED)
                (_CONTROL / _RESTORING).unlink()
            return {"state": state}
        except BaseException:
            _mark(_FAILED)
            raise
        finally:
            _state["importing"] = False
            _thaw(stopped)
            source.unlink(missing_ok=True)


def _refusal(request: Dict[str, Any]) -> Dict[str, Any]:
    """Whether the guard refused the staged command, read and cleared once."""
    name = request.get("name", "")
    if not re.fullmatch(r"[a-f0-9]{32}", name):
        raise ValueError("Invalid staged input name")
    path = _CONTROL / (name + ".refused")
    try:
        code = path.read_text()
    except FileNotFoundError:
        return {"refused": False}
    path.unlink(missing_ok=True)
    return {"refused": True, "code": code}


def _remove(request: Dict[str, Any]) -> Dict[str, Any]:
    # Cleanup must also work on a failed or expired computer, so only the name is checked.
    _transfer_file(request["name"]).unlink(missing_ok=True)
    return {}


def _open_directory(name: str, parent: Optional[int] = None) -> int:
    """Open a directory the agent controls without following a link at any step."""
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _read_small(name: str, parent: int, limit: int = 65536) -> bytes:
    """Read a short regular file the agent controls, relative to an opened directory."""
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Not a regular file")
        return os.read(descriptor, limit)
    finally:
        os.close(descriptor)


def _busy() -> bool:
    """A runtime worker is alive for an unfinished job. A job orphaned by a lost
    process must not keep the session awake, so a status file alone does not count.

    The jobs directory belongs to the agent, so it is walked through directory
    descriptors that never follow a link, and at most 1000 entries are looked at.
    """
    try:
        runtime = _open_directory(str(_RUNTIME))
    except OSError:
        return False
    try:
        jobs = _open_directory("jobs", runtime)
    except OSError:
        os.close(runtime)
        return False
    try:
        with os.scandir(jobs) as entries:
            for count, entry in enumerate(entries):
                if count >= 1000:
                    break
                try:
                    job = _open_directory(entry.name, jobs)
                except OSError:
                    continue
                try:
                    try:
                        os.stat("result.json", dir_fd=job, follow_symlinks=False)
                        continue
                    except FileNotFoundError:
                        pass
                    pid = json.loads(_read_small("status.json", job)).get("pid")
                    if type(pid) is int and pid > 1 and Path(f"/proc/{pid}").stat().st_uid == _USER:
                        return True
                except (OSError, ValueError, AttributeError):
                    continue
                finally:
                    os.close(job)
    finally:
        os.close(jobs)
        os.close(runtime)
    return False


def _ping_reply() -> Dict[str, Any]:
    # time_of_last_update is when the status changed. Sending the current time on
    # every ping keeps AgentCore from ever treating the session as idle.
    status = "HealthyBusy" if _busy() else "Healthy"
    if status != _ping["status"]:
        _ping.update(status=status, since=int(time.time()))
    return {"status": status, "time_of_last_update": _ping["since"]}


_OPERATIONS = {
    "claim": _claim,
    "describe": _describe,
    "peek": _peek,
    "rpc": _rpc,
    "stage": _stage,
    "export": _export,
    "get": _get,
    "put": _put,
    "import": _import,
    "remove": _remove,
    "refusal": _refusal,
}


# Caller check


def _decode_address(value: str) -> Tuple[str, int]:
    """Decode an address from /proc/net/tcp or tcp6, which stores 32-bit words little-endian."""
    host, port = value.split(":")
    raw = bytes.fromhex(host)
    if len(raw) == 4:
        return socket.inet_ntop(socket.AF_INET, raw[::-1]), int(port, 16)
    words = b"".join(raw[index : index + 4][::-1] for index in range(0, 16, 4))
    return socket.inet_ntop(socket.AF_INET6, words), int(port, 16)


def _socket_table() -> List[str]:
    lines: List[str] = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines.extend(Path(table).read_text().splitlines()[1:])
        except OSError:
            continue
    return lines


def _local_peer_uid(address: Tuple[str, int]) -> Optional[int]:
    """The owner of the socket at ``address`` if it lives in this microVM and talks to us."""
    peer_host, peer_port = address[0], address[1]
    peer = ipaddress.ip_address(peer_host)
    if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped:
        peer = peer.ipv4_mapped
    for line in _socket_table():
        fields = line.split()
        local, remote, state, uid = _decode_address(fields[1]), _decode_address(fields[2]), fields[3], int(fields[7])
        if local[1] != peer_port or remote[1] != _PORT:
            continue
        host = ipaddress.ip_address(local[0])
        if isinstance(host, ipaddress.IPv6Address) and host.ipv4_mapped:
            host = host.ipv4_mapped
        if host != peer:
            continue
        # Only an ESTABLISHED socket still has its owner: once a client closes its
        # end, the kernel reports the orphaned socket as UID 0.
        return uid if state == "01" else None
    return None


def _trusted(address: Tuple[str, int]) -> bool:
    """AgentCore's forwarder connects over loopback as its own user; agent code is UID 1000.

    Anything else is refused: a non-loopback peer, and a loopback peer whose socket
    is closed or missing, since its owner can no longer be known.
    """
    host = ipaddress.ip_address(address[0])
    if isinstance(host, ipaddress.IPv6Address) and host.ipv4_mapped:
        host = host.ipv4_mapped
    if not host.is_loopback:
        return False
    uid = _local_peer_uid(address)
    return uid is not None and uid != _USER


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        return

    def _reply(self, body: Dict[str, Any]) -> None:
        payload = json.dumps(body, allow_nan=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path != "/ping":
            self.close_connection = True
            self._reply({"ok": False, "error": "Unknown path"})
            return
        self._reply(_ping_reply())

    def do_POST(self) -> None:
        if self.path != "/invocations" or not _trusted(self.client_address):
            # The body is not read, so the connection cannot carry another request.
            self.close_connection = True
            self._reply({"ok": False, "error": "PermissionError: Forbidden"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= _MAX_BODY:
                self.close_connection = True
                raise ValueError("Invocation body is empty or too large")
            request = json.loads(self.rfile.read(length))
            operation = _OPERATIONS[request.pop("op")]
            # Errors travel in the body: AgentCore turns a non-2xx agent reply into an
            # opaque service error that would hide the reason from the provider.
            self._reply({"ok": True, "value": operation(request)})
        except Exception as error:
            reply = {"ok": False, "error": f"{type(error).__name__}: {error}"[:2000]}
            if isinstance(error, _Refused):
                reply["code"] = error.code
            self._reply(reply)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # Skip the stdlib's reverse DNS lookup of the bind address.
        import socketserver

        socketserver.TCPServer.server_bind(self)
        self.server_name = "agentcore-sandbox"
        self.server_port = self.server_address[1]


# Processes started by the server


def _guarded_exec(arguments: List[str]) -> None:
    """Check the claim and the handle's identity, then run the command as UID 1000.

    Every refusal before the command starts exits 125 with "refusing to run", so the
    provider can tell that nothing ran and leave compute alone.
    """
    name: Optional[str] = None
    try:
        expect: Optional[Dict[str, str]] = None
        if arguments[:1] == ["--expect"]:
            config, _, incarnation = arguments[1].partition(":")
            expect, arguments = {"config": config, "incarnation": incarnation}, arguments[2:]
        if arguments[:1] != ["--stdin"] or len(arguments) != 2 or expect is None:
            raise ValueError("usage: exec --expect CONFIG:INCARNATION --stdin NAME")
        name = arguments[1]
        if not re.fullmatch(r"[a-f0-9]{32}", name):
            name = None
            raise ValueError("Invalid staged input name")
        # The runner is part of this package and starts from this interpreter, so the
        # claimed PATH cannot substitute another program for it.
        argv = [sys.executable, "-I", "-m", "agno.sandbox._exec"]
        claim = _retire_if_unclaimed()
        if claim is not None and expect != {
            "config": claim["metadata"].get("config"),
            "incarnation": claim["incarnation"],
        }:
            raise _Refused("identity", "Computer identity mismatch: this is not the computer the handle names")
        claim = _begin_work(claim)
        path = _CONTROL / (name + ".stdin")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        os.unlink(path)
        os.dup2(descriptor, 0)
        os.close(descriptor)
        environment = _environment(claim)
        _drop_privileges()
        os.chdir(_WORKSPACE)
    except Exception as error:
        code = error.code if isinstance(error, _Refused) else "error"
        if name is not None:
            # Root-only proof that nothing ran: code that runs after the privilege
            # drop can print the same message and exit code, but cannot write here.
            try:
                _write_private(_CONTROL / (name + ".refused"), code.encode())
            except OSError:
                pass
        sys.stderr.write(f"AgentCore computer refusing to run [{code}]: {type(error).__name__}: {error}\n")
        sys.exit(_GUARD_EXIT)
    os.execve(argv[0], argv, environment)


def _checkpoint_capture() -> None:
    """Run as UID 1000: write one validated checkpoint archive of the managed roots to stdout."""
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

    job = json.loads(sys.stdin.buffer.read())
    roots = {name: Path(path) for name, path in job["roots"].items()}
    roots["native"].mkdir(mode=0o700, exist_ok=True)
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-capture-") as directory:
        output = Path(directory) / "checkpoint.tar"
        archive.capture(roots, output, state=job["state"], exclude=job["exclude"])
        with output.open("rb") as stream:
            shutil.copyfileobj(stream, sys.stdout.buffer)
        sys.stdout.buffer.flush()


def _checkpoint_restore(arguments: str) -> None:
    """Run as UID 1000: restore the archive on stdin into the empty managed roots."""
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

    job = json.loads(arguments)
    roots = {name: Path(path) for name, path in job["roots"].items()}
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-restore-") as directory:
        source, staging = Path(directory) / "checkpoint", Path(directory) / "restored"
        with source.open("xb") as stream:
            shutil.copyfileobj(sys.stdin.buffer, stream)
        # Inside the computer, so absolute links name the paths they were captured with.
        state = archive.restore(source, staging, absolute_links=True)
        for name, target in roots.items():
            target.mkdir(mode=0o700, exist_ok=True)
            if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
                raise SystemExit("Restore requires an empty, unused generation")
        for name, target in roots.items():
            # An archive may record a read-only root; its entries must still move out.
            (staging / name).chmod(0o700)
            for entry in (staging / name).iterdir():
                shutil.move(str(entry), str(target / entry.name))
            # The managed roots stay private whatever mode the archive recorded.
            target.chmod(0o700)
    sys.stdout.write(json.dumps(state))


def main() -> None:
    command = sys.argv[1:2]
    if command == ["serve"]:
        # Inherited by everything this server starts, and harmless to root itself.
        _no_new_privileges()
        # Created before serving, so the lifecycle lock and refusals work on a
        # microVM that was never claimed.
        _control_dir()
        threading.Thread(target=_sweeper, daemon=True).start()
        _Server(("0.0.0.0", _PORT), _Handler).serve_forever()
    elif command == ["exec"]:
        _guarded_exec(sys.argv[2:])
    elif command == ["checkpoint-capture"]:
        _checkpoint_capture()
    elif command == ["checkpoint-restore"] and len(sys.argv) == 3:
        _checkpoint_restore(sys.argv[2])
    else:
        sys.exit("usage: python -I -m agno.sandbox.agentcore.server serve | exec [--stdin NAME] -- ARGV...")


if __name__ == "__main__":
    main()
