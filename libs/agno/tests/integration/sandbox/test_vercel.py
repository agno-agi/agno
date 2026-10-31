"""Live Vercel acceptance: bootstrap, guard, lifecycle, checkpoint transfer and the four user paths.

These tests create billable Vercel computers. They run only when AGNO_TEST_VERCEL=1 and
AGNO_TEST_VERCEL_WHEEL names a wheel built from this checkout (cd libs/agno && uv build --wheel).
Credentials resolve through the SDK (OIDC, or VERCEL_TOKEN with VERCEL_TEAM_ID and VERCEL_PROJECT_ID);
nothing here reads them. The public-path tests also need AGNO_TEST_SANDBOX_DB_URL for Postgres, and the
native tests need a model key. Every computer a test creates is destroyed in its fixture.
"""

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, Tuple
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from agno.db.postgres import PostgresDb
from agno.run.base import RunStatus
from agno.sandbox import _harness
from agno.sandbox.base import SandboxError, SandboxHandle
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits, CheckpointRef, FileCheckpointStore
from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.fixture import FixtureAgent
from agno.sandbox.postgres import _SandboxStore
from agno.sandbox.vercel import VercelCheckpointTransfer, VercelSandbox, guard
from agno.sandbox.vercel import sandbox as provider_module
from agno.sandbox.vercel.transfer import VERCEL_NATIVE_EXCLUSIONS

WHEEL = os.environ.get("AGNO_TEST_VERCEL_WHEEL")
DB_URL = os.environ.get("AGNO_TEST_SANDBOX_DB_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("AGNO_TEST_VERCEL") != "1" or not WHEEL,
        reason="Set AGNO_TEST_VERCEL=1 and AGNO_TEST_VERCEL_WHEEL to create billable Vercel computers",
    ),
]
needs_database = pytest.mark.skipif(not DB_URL, reason="Set AGNO_TEST_SANDBOX_DB_URL for the public path")
FIXTURE_ENV = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}


class Tracker:
    """Every computer a test creates, so that none outlives it."""

    def __init__(self) -> None:
        # One entry per successful acreate call, adopted or new: tests that count calls read this.
        self.created: List[Tuple[VercelSandbox, SandboxHandle]] = []
        # One entry per physical computer those calls returned: tests that count computers read this.
        self.computers: Dict[str, Tuple[VercelSandbox, SandboxHandle]] = {}

    def watch(self, provider: VercelSandbox) -> VercelSandbox:
        original = provider.acreate

        async def create(session_id, **kwargs):
            handle = await original(session_id, **kwargs)
            self.created.append((provider, handle))
            self.computers.setdefault(handle.provider_ref, (provider, handle))
            return handle

        provider.acreate = create  # type: ignore[method-assign]
        return provider

    async def cleanup(self) -> None:
        # Every computer is tried even if an earlier one fails; the failures are raised together afterwards.
        failures = []
        for provider, handle in self.computers.values():
            try:
                await provider.adestroy(handle)
                if await provider.aget(handle.provider_ref) is not None:
                    raise AcceptanceFailure("it still exists after being destroyed")
            except Exception as error:
                failures.append((handle.provider_ref, error))
        if failures:
            raise AcceptanceFailure(
                "Cleanup failed for " + "; ".join(f"{ref}: {type(error).__name__}: {error}" for ref, error in failures)
            ) from failures[0][1]


class AcceptanceFailure(AssertionError):
    """A live acceptance step did not establish what it exists to establish."""


def assert_adopted(tracker: Tracker, first: SandboxHandle, second: SandboxHandle) -> None:
    """A second create call adopted the computer the first made: the same handle, and one physical computer in all."""
    if second != first:
        raise AcceptanceFailure(f"adoption returned another computer: {first.provider_ref} then {second.provider_ref}")
    if len(tracker.computers) != 1:
        raise AcceptanceFailure(f"{len(tracker.computers)} computers exist after adoption, not one")


CONTROL_PATHS = ("/opt/agno/control", "/opt/agno/ENV", "/opt/agno/inbox", "/opt/agno/export", "/opt/agno/stage")

# Runs in the guest as the agent. A name that shows up in a listing says nothing about whether a file's content
# is reachable, so a file is opened for reading (and closed at once; nothing is read) and a directory is both
# listed and entered. EACCES is the one expected denial; any other error is reported under its errno name.
CONTROL_PROBE = r"""
import errno, json, os, stat, sys


def attempt(call):
    try:
        call()
    except OSError as error:
        return "denied" if error.errno == errno.EACCES else "error:" + errno.errorcode.get(error.errno, str(error.errno))
    return "allowed"


def open_for_read(path):
    os.close(os.open(path, os.O_RDONLY | os.O_NOFOLLOW))


def probe(paths):
    report = {}
    for path in paths:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            report[path] = {"kind": "missing"}
            continue
        except OSError as error:
            report[path] = {"kind": "error:" + errno.errorcode.get(error.errno, str(error.errno))}
            continue
        if stat.S_ISREG(info.st_mode):
            kind, ops = "file", {"read_open": attempt(lambda: open_for_read(path))}
        elif stat.S_ISDIR(info.st_mode):
            kind, ops = "dir", {
                "list": attempt(lambda: os.listdir(path)),
                "traverse": attempt(lambda: os.stat(os.path.join(path, "."))),
            }
        else:
            kind, ops = ("symlink" if stat.S_ISLNK(info.st_mode) else "other"), {}
        report[path] = {"kind": kind, "uid": info.st_uid, "mode": format(stat.S_IMODE(info.st_mode), "04o"), "ops": ops}
    return report


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1:])))
"""
_OPERATIONS = {"file": ("read_open",), "dir": ("list", "traverse")}
_WORDS = {"read_open": "open for reading", "list": "list", "traverse": "traverse"}


async def assert_control_paths_denied(
    provider: Any, handle: SandboxHandle, paths: Tuple[str, ...] = CONTROL_PATHS
) -> Dict[str, Any]:
    """The agent is denied every access operation on each protected path, and each path is the expected kind of object.

    Only an expected permission denial counts. An allowed operation, a missing or wrong-kind target, an unexpected
    error or an incomplete answer is a failure, never a pass. Returns the per-path answer (kinds, owners, modes and
    one word per operation; never content).
    """
    result = await provider.aexec(handle, ["python", "-c", CONTROL_PROBE, *paths])
    if result.timed_out or result.exit_code != 0:
        raise AcceptanceFailure(f"the permission probe did not run to completion (exit status {result.exit_code})")
    try:
        observed = json.loads(result.stdout)
    except ValueError:
        raise AcceptanceFailure("the permission probe's answer is not JSON") from None
    if not isinstance(observed, dict):
        raise AcceptanceFailure("the permission probe returned no per-path answer")
    problems: List[str] = []
    for path in paths:
        entry = observed.get(path)
        if not isinstance(entry, dict):
            problems.append(f"{path} was not probed")
            continue
        want = "file" if os.path.basename(path) == "ENV" else "dir"
        kind = entry.get("kind")
        if kind == "missing":
            problems.append(f"{path} is missing")
        elif kind != want:
            problems.append(f"{path} is {'a directory' if kind == 'dir' else 'a ' + str(kind)}, expected a {want}")
        elif not isinstance(entry.get("ops"), dict) or set(entry["ops"]) != set(_OPERATIONS[want]):
            problems.append(f"{path}: the probe did not report exactly {list(_OPERATIONS[want])}")
        else:
            for name in _OPERATIONS[want]:
                outcome = entry["ops"][name]
                if outcome == "allowed":
                    problems.append(f"the agent can {_WORDS[name]} {path}")
                elif outcome != "denied":
                    problems.append(f"{path}: {name} gave {str(outcome)[:40]!r}, not a permission denial")
    if problems:
        raise AcceptanceFailure("; ".join(problems))
    return observed


@dataclass(frozen=True)
class OwnedComputer:
    name: str
    session_id: str


async def cancel_at_bootstrap_entry(
    provider: VercelSandbox, session_id: str, *, agent_id: str, deadline: float = 120.0
) -> OwnedComputer:
    """Cancel acreate at the moment its bootstrap is entered, for a computer whose name and session are known.

    The bootstrap is held at its first line, so this cancels *at bootstrap entry*, not during an install command.
    Everything else is the provider's own: the create call, the cancellation handling and the cleanup that
    stops the exact session and deletes the box. A cancellation that arrives while the create call has not yet
    been acknowledged is the lost-reply case and is not what this establishes, so it fails.
    """
    entered: "asyncio.Future[OwnedComputer]" = asyncio.get_running_loop().create_future()

    async def hold(session: Any, *args: Any, **kwargs: Any) -> None:
        if not entered.done():
            entered.set_result(OwnedComputer(session.sandbox_name, session.id))
        await asyncio.sleep(3600)  # cleaned up by the cancellation below; never allowed to proceed

    provider._bootstrap = hold  # type: ignore[method-assign]
    task = asyncio.ensure_future(provider.acreate(session_id, agent_id=agent_id))
    owned: Optional[OwnedComputer] = None
    try:
        try:
            owned = await asyncio.wait_for(asyncio.shield(entered), deadline)
        except asyncio.TimeoutError:
            raise AcceptanceFailure(f"the bootstrap was not entered within {deadline:.0f}s") from None
        task.cancel()
        try:
            await asyncio.wait_for(task, deadline)
        except asyncio.CancelledError:
            pass
        else:
            raise AcceptanceFailure("acreate returned although it was cancelled")
        if await provider.aget(owned.name) is not None:
            raise AcceptanceFailure(f"{owned.name} still exists after the cancelled create")
        return owned
    except BaseException:
        # Whatever went wrong, leave nothing behind: remove the box by the handle it would have had.
        task.cancel()
        if owned is not None and await provider.aget(owned.name) is not None:
            await provider.adestroy(
                SandboxHandle(
                    provider_ref=owned.name,
                    name=f"{owned.name}/{owned.session_id}",
                    agent_id=agent_id,
                    session_id=session_id,
                    generation=1,
                    state="created",
                    config_digest=provider._digest(session_id, agent_id, 1, {}),
                )
            )
        raise


# --- a capture killed while frozen, driven from the host -------------------------------------------------


@dataclass(frozen=True)
class Writer:
    pid: int
    start: str  # start time in ticks: with the pid, the process's identity


@dataclass(frozen=True)
class CaptureOutcome:
    code: int
    stderr: str


class CaptureRun(Protocol):
    async def finished(self) -> bool: ...

    async def outcome(self) -> CaptureOutcome: ...

    async def close(self) -> None: ...


class Guest(Protocol):
    """What the crash-recovery orchestration needs from a computer; the live one speaks to the SDK."""

    async def start_writer(self) -> Writer: ...

    async def stage_capture_request(self, name: str, request: Dict[str, Any]) -> None: ...

    async def start_capture(self, name: str) -> CaptureRun: ...

    async def guard_pid(self, name: str) -> Optional[int]: ...

    async def journal_intents(self) -> List[Tuple[int, str]]: ...

    async def process(self, pid: int) -> Optional[Tuple[str, str]]: ...

    async def kill(self, pid: int) -> None: ...

    async def next_operation(self) -> None: ...

    async def ticks(self) -> str: ...

    async def cleanup(self, name: str, writer: Optional[Writer]) -> None: ...


# The production request for a capture, as the transfer builds it.
CAPTURE_REQUEST = {
    "state": {"turn": 1},
    "exclude": list(VERCEL_NATIVE_EXCLUSIONS),
    "limits": asdict(CheckpointLimits()),
}
KILLED = (137, -9)  # a process the guard waits for, ended by SIGKILL: the shell's convention, or the signal itself


async def recover_a_capture_killed_while_frozen(
    guest: Guest, *, deadline: float = 120.0, poll: float = 0.2, resume_deadline: float = 30.0
) -> Writer:
    """Kill the guard mid-capture, once the writer is provably stopped and journaled, and prove the next command resumes it.

    Every way this can end without having exercised that path raises ``AcceptanceFailure``: a refused or
    failed capture, a capture that finished before the frozen window was seen, a guard that was not found, a
    death by anything but the kill, and a writer that does not resume with the same identity and progress.
    """
    name = uuid4().hex
    writer: Optional[Writer] = None
    run: Optional[CaptureRun] = None
    try:
        writer = await guest.start_writer()
        await guest.stage_capture_request(name, CAPTURE_REQUEST)
        run = await guest.start_capture(name)
        end = time.monotonic() + deadline
        while True:
            if await run.finished():
                result = await run.outcome()
                raise AcceptanceFailure(
                    f"the capture ended (exit {result.code}) before the frozen window was observed: {result.stderr[-300:]!r}"
                )
            state = await guest.process(writer.pid)
            intents = await guest.journal_intents()
            if (
                state is not None
                and state[1] == writer.start
                and state[0].startswith("T")
                and any(pid == writer.pid and ident.rpartition(":")[2] == writer.start for pid, ident in intents)
            ):
                break
            if time.monotonic() > end:
                raise AcceptanceFailure("the writer was never seen stopped with a journaled intent")
            await asyncio.sleep(poll)
        victim = await guest.guard_pid(name)
        if victim is None:
            raise AcceptanceFailure("the guard process for this request was not found")
        await guest.kill(victim)
        result = await asyncio.wait_for(run.outcome(), deadline)
        if result.code not in KILLED or guard.REFUSAL_PREFIX in result.stderr:
            raise AcceptanceFailure(
                f"the capture did not end by the kill (exit {result.code}): {result.stderr[-300:]!r}"
            )
        stopped = await guest.process(writer.pid)
        if stopped is None or not stopped[0].startswith("T"):
            raise AcceptanceFailure("the writer was not still stopped after the guard died")
        before = await guest.ticks()
        await guest.next_operation()  # an ordinary command: its admission recovers the interrupted capture
        end = time.monotonic() + resume_deadline
        while True:
            state = await guest.process(writer.pid)
            if state is None or state[1] != writer.start:
                raise AcceptanceFailure("the writer is gone or is a different process")
            if not state[0].startswith("T") and await guest.ticks() != before:
                return writer
            if time.monotonic() > end:
                raise AcceptanceFailure("the writer did not resume and make progress after the next command")
            await asyncio.sleep(poll)
    finally:
        try:
            if run is not None:
                await run.close()
        finally:
            await guest.cleanup(name, writer)


WRITER_SOURCE = """
import time
while True:
    open('/workspace/tick', 'w').write(str(time.time()))
    time.sleep(0.1)
"""


class SdkGuest:
    """The live computer: a session of the Vercel SDK, driven the way the production transfer drives the guard."""

    def __init__(self, provider: VercelSandbox, handle: SandboxHandle) -> None:
        self.provider, self.handle = provider, handle

    async def _session(self, client: Any) -> Any:
        return (await client.get_sandbox(name=self.handle.provider_ref)).current_session

    async def _root(self, argv: List[str]) -> Any:
        client = provider_module._new_client(self.provider.options)
        try:
            return await (await self._session(client)).run_process(
                argv[0], argv[1:], sudo=True, capture_output=True, kill_after=60
            )
        finally:
            await provider_module._close(client)

    async def start_writer(self) -> Writer:
        await self.provider.aexec(self.handle, ["sh", "-c", "cat > /tmp/writer.py"], stdin=WRITER_SOURCE.encode())
        out = await self.provider.aexec(
            self.handle, ["sh", "-c", "nohup python /tmp/writer.py >/dev/null 2>&1 & echo $!"]
        )
        pid = int(out.stdout.strip())
        state = await self.process(pid)
        if state is None:
            raise AcceptanceFailure("the writer did not start")
        return Writer(pid, state[1])

    async def stage_capture_request(self, name: str, request: Dict[str, Any]) -> None:
        client = provider_module._new_client(self.provider.options)
        try:
            await (await self._session(client)).fs.write_bytes(
                f"{guard.INBOX}/{name}.json", json.dumps(request).encode(), mode=0o600
            )
        finally:
            await provider_module._close(client)

    async def start_capture(self, name: str) -> CaptureRun:
        client = provider_module._new_client(self.provider.options)
        try:
            process = await (await self._session(client)).create_process(
                guard.PYTHON, ["-I", "-m", "agno.sandbox.vercel.guard", "capture", name], sudo=True
            )
        except BaseException:
            await provider_module._close(client)  # nobody holds the client yet
            raise
        return _SdkCapture(client, process)  # the capture owns the client from here

    async def guard_pid(self, name: str) -> Optional[int]:
        # Anchored on the interpreter, so neither this shell nor sudo's wrapper (whose command lines differ) matches.
        script = (
            "for p in /proc/[0-9]*; do "
            f"tr '\\0' ' ' < $p/cmdline 2>/dev/null | grep -q '^{guard.PYTHON} -I -m agno.sandbox.vercel.guard capture {name} ' "
            "&& echo ${p#/proc/}; done"
        )
        found = (await self._root(["sh", "-c", script])).stdout.split()
        return int(found[0]) if len(found) == 1 else None

    async def journal_intents(self) -> List[Tuple[int, str]]:
        result = await self._root(["cat", "/opt/agno/control/freeze.journal"])
        intents = []
        for line in (result.stdout or "").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("op") == "intent":
                intents.append((record["pid"], record["id"]))
        return intents

    async def process(self, pid: int) -> Optional[Tuple[str, str]]:
        result = await self._root(["cat", f"/proc/{pid}/stat"])
        parsed = guard.parse_stat(result.stdout or "") if result.returncode == 0 else None
        return None if parsed is None else (parsed["state"], parsed["start"])

    async def kill(self, pid: int) -> None:
        await self._root(["kill", "-9", str(pid)])

    async def next_operation(self) -> None:
        await self.provider.aexec(self.handle, ["true"])

    async def ticks(self) -> str:
        # As root, outside the guard: a read through the provider would run the guard's admission and could
        # itself recover the interrupted capture before the ordinary command that is meant to.
        return (await self._root(["cat", "/workspace/tick"])).stdout or ""

    async def cleanup(self, name: str, writer: Optional[Writer]) -> None:
        # Best effort and bounded; the computer itself is removed by the test's tracker.
        for step in (
            ["kill", "-9", str(writer.pid)] if writer else None,
            ["rm", "-f", f"{guard.INBOX}/{name}.json", f"{guard.EXPORT}/{name}.tar"],
        ):
            if step is not None:
                try:
                    await asyncio.wait_for(self._root(step), 60)
                except Exception as error:
                    print(f"cleanup step {step[0]} failed: {type(error).__name__}")


class _SdkCapture:
    def __init__(self, client: Any, process: Any) -> None:
        self.client, self.process = client, process
        self._result: Optional[CaptureOutcome] = None

    async def close(self) -> None:
        """Release the host-side client only; the remote process is neither waited for nor stopped."""
        await provider_module._close(self.client)

    async def finished(self) -> bool:
        if self._result is not None:
            return True
        await self.process.refresh()
        return str(getattr(self.process.status, "value", self.process.status)).lower() == "exited"

    async def outcome(self) -> CaptureOutcome:
        if self._result is None:
            code = await self.process.wait()
            errors = ""
            try:
                _, errors = await self.process.communicate()
            except Exception as error:  # the exit code alone still distinguishes a kill from a refusal
                print(f"capture stderr unavailable: {type(error).__name__}")
            self._result = CaptureOutcome(code, errors or "")
        return self._result


@pytest_asyncio.fixture
async def tracker():
    value = Tracker()
    try:
        yield value
    finally:
        await value.cleanup()


def provider_for(tracker: Tracker, tmp_path: Path, **kwargs) -> VercelSandbox:
    kwargs.setdefault("namespace", "test-" + uuid4().hex[:12])
    kwargs.setdefault("checkpoints", FileCheckpointStore(tmp_path / "objects"))
    kwargs.setdefault("env", FIXTURE_ENV)
    return tracker.watch(VercelSandbox(wheel=Path(WHEEL), **kwargs))  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def computer(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    started = time.monotonic()
    handle = await provider.acreate(
        "session", agent_id="coder", env={**FIXTURE_ENV, "SYNTHETIC_MARKER": "marker-value"}
    )
    handle_seconds = time.monotonic() - started
    print(f"bootstrap to usable computer: {handle_seconds:.1f}s")
    return provider, handle


# --- the bootstrap and the guard -------------------------------------------------------------------------


async def test_bootstrap_installs_the_pinned_natives_and_matches_the_hosts_source(computer):
    provider, handle = computer
    assert handle.state == "running"
    found = await provider.afind("session", agent_id="coder", env={**FIXTURE_ENV, "SYNTHETIC_MARKER": "marker-value"})
    assert found == handle
    result = await provider.aexec(handle, ["cat", "/opt/agno/READY"])
    marker = json.loads(result.stdout)
    assert marker["source_digest"] == provider_module._host_digest() and marker["route"] == "wheel"
    installed = marker["installed"]
    for pin in provider_module.NATIVE_PINS:
        name, _, version = pin.partition("==")
        assert installed[name] == version
    assert installed["python"].startswith(provider_module.GUEST_PYTHON) and "git" in installed


async def test_commands_run_as_the_agent_user_with_the_installed_environment_only(computer):
    provider, handle = computer
    result = await provider.aexec(
        handle,
        [
            "python",
            "-c",
            "import json, os; print(json.dumps([os.getuid(), os.getgid(), os.getgroups(), sorted(os.environ)]))",
        ],
    )
    uid, gid, groups, names = json.loads(result.stdout)
    assert (uid, gid, groups) == (2001, 2001, [])
    assert "SYNTHETIC_MARKER" in names and "AGNO_SANDBOX_TEST_RUNTIME" in names
    # The sudo environment of the box is not forwarded.
    assert not [name for name in names if name.startswith("SUDO_")]
    assert set(names) <= {"SYNTHETIC_MARKER", "AGNO_SANDBOX_TEST_RUNTIME", "HOME", "PATH", "LANG", "LC_ALL", "TZ"}
    value = await provider.aexec(handle, ["printenv", "SYNTHETIC_MARKER"])
    assert value.stdout.strip() == "marker-value"


async def test_the_agent_cannot_reach_the_control_state_or_the_staging_directories(computer):
    provider, handle = computer
    print(await assert_control_paths_denied(provider, handle))
    status = await provider.aexec(
        handle, ["sh", "-c", "grep NoNewPrivs /proc/self/status; grep CapEff /proc/self/status"]
    )
    assert "NoNewPrivs:\t1" in status.stdout and "CapEff:\t0000000000000000" in status.stdout


async def test_the_file_api_stages_requests_the_way_the_guard_expects(computer):
    provider, handle = computer
    client = provider_module._new_client(provider.options)
    try:
        sandbox = await client.get_sandbox(name=handle.provider_ref)
        session = sandbox.current_session
        await session.fs.write_bytes("/tmp/probe-staging", b"x", mode=0o600)
        stat = await session.run_process("stat", ["-c", "%u %a", "/tmp/probe-staging"], sudo=True, capture_output=True)
        assert stat.stdout.strip() == "1000 600"
    finally:
        await provider_module._close(client)


async def test_a_command_timeout_stops_the_exact_session(computer):
    provider, handle = computer
    result = await provider.aexec(handle, ["python", "-c", "import time; time.sleep(60)"], timeout=1)
    assert result.timed_out
    assert (await provider.aget(handle.provider_ref)).state == "exited"
    with pytest.raises(SandboxError):
        await provider.aexec(handle, ["true"])


async def test_unicode_and_binary_stdin_survive_the_staged_request(computer):
    provider, handle = computer
    payload = bytes(range(256)) * 64
    result = await provider.aexec(
        handle, ["python", "-c", "import sys; print(len(sys.stdin.buffer.read()))"], stdin=payload
    )
    assert result.stdout.strip() == str(len(payload))


# --- lifecycle -------------------------------------------------------------------------------------------


async def test_tags_round_trip_and_listing_finds_the_box_at_once(computer):
    provider, handle = computer
    started = time.monotonic()
    found = await provider.afind("session", agent_id="coder", env={**FIXTURE_ENV, "SYNTHETIC_MARKER": "marker-value"})
    print(f"listing after create: {time.monotonic() - started:.2f}s")
    assert found is not None and found.provider_ref == handle.provider_ref
    again = await provider.aget(handle.provider_ref)
    assert (again.agent_id, again.session_id, again.generation) == ("coder", "session", 1)


async def test_a_stale_handle_cannot_remove_the_replacement(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    old = await provider.acreate("session", agent_id="coder")
    await provider.adestroy(old)
    replacement = await provider.acreate("session", agent_id="coder")
    assert replacement.provider_ref != old.provider_ref
    await provider.adestroy(old)  # a repeat of the first destroy, as a lost reply would cause
    found = await provider.aget(replacement.provider_ref)
    assert found is not None and found.state == "running"


async def test_create_adopts_the_one_usable_computer_it_finds(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    first = await provider.acreate("session", agent_id="coder")
    second = await provider.acreate("session", agent_id="coder")
    assert len(tracker.created) == 2  # two calls
    assert_adopted(tracker, first, second)  # one computer


async def test_a_create_cancelled_at_bootstrap_entry_removes_its_computer(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    owned = await cancel_at_bootstrap_entry(provider, "session", agent_id="coder")
    # Checked by name, not by listing, which may lag: the computer the cancelled create made is gone.
    assert await provider.aget(owned.name) is None


async def test_identity_values_round_trip_or_fail_loudly(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    long_session = "s" * 200
    try:
        handle = await provider.acreate(long_session, agent_id="a" * 100)
    except SandboxError as error:
        print(f"tag limits: refused long identity values: {error}")
        return
    assert (await provider.aget(handle.provider_ref)).session_id == long_session


# --- direct paths: P1 and P2 -----------------------------------------------------------------------------


def _turn(client, computer, number, prompt, *, sdk="fixture", config=None):
    execution = client.start(
        computer,
        execution_id=f"turn-{number}",
        run_id=f"run-{number}",
        sdk=sdk,
        input=prompt,
        config=config or {},
        execution_timeout=600,
    )
    result = None
    for page in client.pages(execution, timeout=900):
        result = page.result
    assert result is not None and result["type"] == "execution_finished", result
    return result


async def test_p1_two_direct_turns_run_on_one_retained_computer(computer):
    provider, handle = computer
    client = SandboxRuntimeClient(provider)
    first = await asyncio.to_thread(_turn, client, handle, 1, "first")
    second = await asyncio.to_thread(_turn, client, handle, 2, "second")
    assert first["run"]["status"] == second["run"]["status"] == "COMPLETED"
    effects = await provider.aexec(handle, ["cat", "/workspace/fixture-effects.txt"])
    assert effects.stdout.split() == ["run-1", "run-2"]


async def test_the_runtime_worker_outlives_the_command_that_started_it(computer):
    provider, handle = computer
    client = SandboxRuntimeClient(provider)
    # Polls are later commands: the foreground command that started the worker has long since exited.
    result = await asyncio.to_thread(_turn, client, handle, 1, "slow", config={"delay": 8})
    assert result["run"]["status"] == "COMPLETED"


async def test_p2_a_checkpoint_restores_onto_a_new_generation_and_the_turn_continues(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    transfer = VercelCheckpointTransfer(provider, provider.checkpoints)  # type: ignore[arg-type]
    client = SandboxRuntimeClient(provider)
    identity = {"agent_id": "coder", "env": FIXTURE_ENV}
    first = await provider.acreate("session", **identity)
    await asyncio.to_thread(_turn, client, first, 1, "first")
    reference = await transfer.acapture(first, state={"turn": 1})
    await provider.adestroy(first)
    second = await provider.acreate("session", generation=2, **identity)
    assert second.provider_ref != first.provider_ref
    assert await transfer.arestore(second, reference) == {"turn": 1}
    await asyncio.to_thread(_turn, client, second, 2, "second")
    effects = await provider.aexec(second, ["cat", "/workspace/fixture-effects.txt"])
    assert effects.stdout.split() == ["run-1", "run-2"]


async def test_a_restore_onto_a_computer_that_already_ran_is_refused_and_stops_it(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    transfer = VercelCheckpointTransfer(provider, provider.checkpoints)  # type: ignore[arg-type]
    source = await provider.acreate("session", agent_id="coder")
    reference = await transfer.acapture(source, state={"turn": 0})
    await provider.aexec(source, ["true"])
    with pytest.raises(SandboxError):
        await transfer.arestore(source, reference)
    assert (await provider.aget(source.provider_ref)).state == "exited"


async def test_a_capture_killed_while_the_agent_is_frozen_is_recovered_by_the_next_command(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    handle = await provider.acreate("session", agent_id="coder")
    # Enough data that the archive phase lasts; the orchestration waits for the frozen window, not for a delay.
    await provider.aexec(handle, ["sh", "-c", "head -c 300000000 /dev/urandom > /workspace/big.bin"], timeout=300)
    writer = await recover_a_capture_killed_while_frozen(SdkGuest(provider, handle))
    assert writer.pid > 1


WRITERS = """
import os, sys, time

def write(path):
    n = 0
    while True:
        n += 1
        open(path, "w").write(str(n))
        time.sleep(0.05)

kind = sys.argv[1]
if kind == "plain":
    write("/workspace/plain")
elif kind == "child":
    if os.fork() == 0:
        write("/workspace/child")
    else:
        time.sleep(1e6)
elif kind == "session":
    os.setsid()
    write("/workspace/session")
elif kind == "double":
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            write("/workspace/double")
        os._exit(0)
    time.sleep(1e6)
"""


async def test_capture_stops_plain_child_session_changed_and_double_fork_writers(tracker, tmp_path):
    provider = provider_for(tracker, tmp_path)
    transfer = VercelCheckpointTransfer(provider, provider.checkpoints)  # type: ignore[arg-type]
    handle = await provider.acreate("session", agent_id="coder")
    await provider.aexec(handle, ["sh", "-c", "cat > /tmp/writers.py"], stdin=WRITERS.encode())
    for kind in ("plain", "child", "session", "double"):
        await provider.aexec(handle, ["sh", "-c", f"nohup python /tmp/writers.py {kind} >/dev/null 2>&1 &"])
    await asyncio.sleep(1)
    reference = await transfer.acapture(handle, state={"turn": 1})
    # Whatever the archive caught was caught while every writer was stopped: the counters it holds are whole files.
    restored = tmp_path / "restored"
    with provider.checkpoints.open_archive(reference) as archive:  # type: ignore[union-attr]
        CheckpointArchive().restore(archive, restored)
    for kind in ("plain", "child", "session", "double"):
        assert (restored / "workspace" / kind).read_text().isdigit()
    before = (await provider.aexec(handle, ["cat", "/workspace/plain", "/workspace/double"])).stdout
    await asyncio.sleep(1)
    after = (await provider.aexec(handle, ["cat", "/workspace/plain", "/workspace/double"])).stdout
    assert before != after, "the writers were not resumed after the capture"


async def test_real_process_handles_and_the_selector_work_on_the_boxs_kernel(computer):
    provider, handle = computer
    result = await provider.aexec(handle, ["python", "-c", "import os; print(hasattr(os, 'pidfd_open'))"])
    assert result.stdout.strip() == "True"


# --- the public agent path: P3 and P4 --------------------------------------------------------------------


@pytest_asyncio.fixture
async def public(tracker, tmp_path):
    suffix = uuid4().hex[:12]
    db = PostgresDb(
        db_url=DB_URL,
        session_table="vc_sessions_" + suffix,
        runs_table="vc_runs_" + suffix,
        sandbox_table="vc_bindings_" + suffix,
    )
    provider = provider_for(tracker, tmp_path, namespace="vercel-public-" + suffix)
    agent = FixtureAgent(id="coder", db=db, sandbox=provider)
    # The coordinator every run of this agent uses, built once per sandbox and database.
    coordinator = _harness.coordinator(agent)
    try:
        yield agent, coordinator, provider, tmp_path
    finally:
        await tracker.cleanup()
        tracker.created.clear()
        store = coordinator.store
        await store._transaction(lambda c: [t.drop(c) for t in (store.bindings, store.runs, store.sessions)])
        db.db_engine.dispose()


async def _binding(coordinator):
    return await coordinator.store._transaction(
        lambda c: dict(c.execute(select(coordinator.store.bindings)).mappings().one())
    )


async def _effects(coordinator, root: Path):
    record = (await _binding(coordinator))["record"]
    target = root / uuid4().hex
    state = await coordinator.transfer.store.arestore(CheckpointRef(**record["checkpoint"]), target)
    assert state["binding"] == record["checkpoint_identity"]
    return target, (target / "workspace/fixture-effects.txt").read_text().splitlines()


@needs_database
async def test_p3_two_public_turns_restore_a_new_generation_each_time(public, tracker):
    agent, coordinator, provider, root = public
    coordinator.warm_computer_seconds = 0
    first = await agent.arun("first", session_id="session", run_id="first")
    first_record = (await _binding(coordinator))["record"]
    second = await agent.arun("second", session_id="session", run_id="second")
    assert first.status == second.status == RunStatus.completed
    assert first.metadata["sandbox"]["resumed"] is False and second.metadata["sandbox"]["resumed"] is False
    assert (await _binding(coordinator))["record"]["generation"] > first_record["generation"]
    handles = [handle for _, handle in tracker.created]
    assert len({handle.provider_ref for handle in handles}) == len(handles) == 2
    _, effects = await _effects(coordinator, root)
    assert effects == ["first", "second"]
    for handle in handles:
        assert await provider.aget(handle.provider_ref) is None  # each turn's computer was removed


@needs_database
async def test_p3_attachments_are_staged_checkpointed_and_restored_on_a_new_generation(public):
    from agno.media import File, Image

    agent, coordinator, provider, root = public
    coordinator.warm_computer_seconds = 0
    png = b"\x89PNG-fixture"
    await agent.arun(
        "first",
        session_id="session",
        run_id="first",
        images=[Image(content=png, format="png")],
        files=[File(content=b"notes", filename="notes.txt")],
    )
    await agent.arun("second", session_id="session", run_id="second")
    workspace, _ = await _effects(coordinator, root)
    uploads = workspace / "workspace/.agno/uploads/first"
    assert (uploads / "image-1.png").read_bytes() == png and (uploads / "notes.txt").read_bytes() == b"notes"


@needs_database
async def test_p4_the_second_public_turn_reuses_the_running_computer(public, tracker, monkeypatch):
    agent, coordinator, provider, root = public
    coordinator.warm_computer_seconds = 300
    restores = []
    restore = coordinator.transfer.arestore

    async def counted(*args, **kwargs):
        restores.append(args)
        return await restore(*args, **kwargs)

    monkeypatch.setattr(coordinator.transfer, "arestore", counted)
    try:
        first = await agent.arun("first", session_id="session", run_id="first")
        before = (await _binding(coordinator))["record"]
        warm = await provider.aget(tracker.created[0][1].provider_ref)
        assert first.metadata["sandbox"]["resumed"] is False and warm is not None and warm.state == "running"
        second = await agent.arun("second", session_id="session", run_id="second")
        after = (await _binding(coordinator))["record"]
        assert second.status == RunStatus.completed and second.metadata["sandbox"]["resumed"] is True
        assert after["generation"] == before["generation"] and restores == [] and len(tracker.created) == 1
        _, effects = await _effects(coordinator, root)
        assert effects == ["first", "second"]
    finally:
        record = (await _binding(coordinator))["record"]
        await coordinator.aretire_computer("session", agent_id="coder", user_id=record.get("user_id"))
        tracker.created.clear()


# --- native harnesses ------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def native_database(tracker: Tracker) -> AsyncIterator[Tuple[PostgresDb, str]]:
    suffix = uuid4().hex[:12]
    db = PostgresDb(
        db_url=DB_URL, session_table="vc_s_" + suffix, runs_table="vc_r_" + suffix, sandbox_table="vc_b_" + suffix
    )
    try:
        yield db, suffix
    finally:
        await tracker.cleanup()
        tracker.created.clear()
        store = _SandboxStore(db)
        await store._transaction(lambda c: [t.drop(c) for t in (store.bindings, store.runs, store.sessions)])
        db.db_engine.dispose()


async def _recall(agent: Any) -> Any:
    await agent.arun(
        "Remember the codeword BLUE-HERON. Do not write it to a file. Reply with just OK.", session_id="session"
    )
    return await agent.arun("What codeword did I ask you to remember?", session_id="session")


@needs_database
@pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
    reason="Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN",
)
async def test_claude_recalls_its_conversation_on_a_restored_computer(tracker, tmp_path, native_database):
    from agno.agents.claude import ClaudeAgent

    db, suffix = native_database
    agent = ClaudeAgent(
        id="coder",
        model="claude-sonnet-5-5",
        permission_mode="bypassPermissions",
        allowed_tools=[],
        db=db,
        sandbox=provider_for(
            tracker,
            tmp_path,
            namespace="vercel-claude-" + suffix,
            env={k: os.environ[k] for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN") if k in os.environ},
        ),
    )
    coordinator = _harness.coordinator(agent)
    coordinator.warm_computer_seconds = 0
    recalled = await _recall(agent)
    assert "BLUE-HERON" in str(recalled.content) and len({h.provider_ref for _, h in tracker.created}) == 2


@needs_database
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="Set OPENAI_API_KEY")
async def test_codex_recalls_its_conversation_on_a_restored_computer(tracker, tmp_path, native_database):
    from agno.agents.codex import CodexAgent

    db, suffix = native_database
    agent = CodexAgent(
        id="coder",
        db=db,
        sandbox=provider_for(
            tracker, tmp_path, namespace="vercel-codex-" + suffix, env={"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]}
        ),
        sandbox_mode="full-access",
        model="gpt-5.6-luna",
        reasoning_effort="low",
    )
    coordinator = _harness.coordinator(agent)
    coordinator.warm_computer_seconds = 0
    recalled = await _recall(agent)
    assert "BLUE-HERON" in str(recalled.content) and len({h.provider_ref for _, h in tracker.created}) == 2


@needs_database
@pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
    reason="Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN",
)
async def test_claude_recalls_its_conversation_on_a_reused_warm_computer(tracker, tmp_path, native_database):
    from agno.agents.claude import ClaudeAgent

    db, suffix = native_database
    agent = ClaudeAgent(
        id="coder",
        model="claude-sonnet-5-5",
        permission_mode="bypassPermissions",
        allowed_tools=[],
        db=db,
        sandbox=provider_for(
            tracker,
            tmp_path,
            namespace="vercel-claude-warm-" + suffix,
            env={k: os.environ[k] for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN") if k in os.environ},
        ),
    )
    coordinator = _harness.coordinator(agent)
    coordinator.warm_computer_seconds = 300
    try:
        recalled = await _recall(agent)
        assert "BLUE-HERON" in str(recalled.content)
        assert recalled.metadata["sandbox"]["resumed"] is True and len(tracker.created) == 1
    finally:
        record = (await _binding(coordinator))["record"]
        await coordinator.aretire_computer("session", agent_id="coder", user_id=record.get("user_id"))


@needs_database
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="Set OPENAI_API_KEY")
async def test_codex_recalls_its_conversation_on_a_reused_warm_computer(tracker, tmp_path, native_database):
    from agno.agents.codex import CodexAgent

    db, suffix = native_database
    agent = CodexAgent(
        id="coder",
        db=db,
        sandbox=provider_for(
            tracker,
            tmp_path,
            namespace="vercel-codex-warm-" + suffix,
            env={"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]},
        ),
        sandbox_mode="full-access",
        model="gpt-5.6-luna",
        reasoning_effort="low",
    )
    coordinator = _harness.coordinator(agent)
    coordinator.warm_computer_seconds = 300
    try:
        recalled = await _recall(agent)
        assert "BLUE-HERON" in str(recalled.content)
        assert recalled.metadata["sandbox"]["resumed"] is True and len(tracker.created) == 1
    finally:
        record = (await _binding(coordinator))["record"]
        await coordinator.aretire_computer("session", agent_id="coder", user_id=record.get("user_id"))
