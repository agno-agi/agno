"""AgentCore sandbox contracts against a fake data plane and the real in-computer server code."""

import base64
import dataclasses
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("boto3")

from botocore.exceptions import ClientError, EndpointConnectionError

import agno.sandbox.agentcore.sandbox as agentcore_sandbox
from agno.sandbox.agentcore import AgentCoreCheckpointTransfer, AgentCoreSandbox, server
from agno.sandbox.agentcore.sandbox import _Refusal
from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import CheckpointRef, FileCheckpointStore

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/agno_sandbox-abc123"


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "Operation")


class Data:
    """Answers like the bedrock-agentcore data plane in front of the AgentCore server."""

    def __init__(self):
        self.claims, self.incarnations, self.retired = {}, {}, set()
        self.invokes, self.commands, self.stops, self.staged = [], [], [], {}
        self.conflicts = 0
        self.conflict_code = "RetryableConflictException"
        self.command_reply = {"exitCode": 0, "status": "COMPLETED"}
        self.command_stdout = json.dumps({"exit_code": 0, "stdout": "hi", "stderr": ""})
        self.command_stderr = ""
        self.command_error = None
        self.rpc_reply = {"status": 200, "body": '{"version": 1}'}
        # The code the guard recorded for a refused command, as only root can.
        self.refusal_code = None

    def invoke_agent_runtime(self, **kwargs):
        self.invokes.append(kwargs)
        if self.conflicts:
            self.conflicts -= 1
            raise client_error(self.conflict_code)
        request = json.loads(kwargs["payload"])
        session, operation = kwargs["runtimeSessionId"], request.pop("op")
        reply = {"ok": True}
        if operation == "claim":
            existing = self.claims.get(session)
            if session in self.retired:
                reply = {"ok": False, "error": "_Refused: retired", "code": "unusable"}
            elif existing and existing != request["metadata"]:
                reply = {
                    "ok": False,
                    "error": "_Refused: already claimed with a different identity",
                    "code": "identity",
                }
            else:
                self.claims[session] = request["metadata"]
                self.incarnations.setdefault(session, os.urandom(8).hex())
                reply["value"] = {
                    "metadata": request["metadata"],
                    "incarnation": self.incarnations[session],
                    "created": existing is None,
                }
        elif operation == "refusal":
            reply["value"] = {"refused": self.refusal_code is not None, "code": self.refusal_code}
        elif operation in ("describe", "peek"):
            claim = self.claims.get(session)
            reply["value"] = {"claimed": claim is not None}
            if claim:
                reply["value"].update(metadata=claim, incarnation=self.incarnations[session])
            elif operation == "describe":
                self.retired.add(session)
            else:
                reply["value"]["retired"] = session in self.retired
        else:
            claim = self.claims.get(session)
            expected = claim and {"config": claim["config"], "incarnation": self.incarnations[session]}
            if claim is None:
                return self._reply({"ok": False, "error": "_Refused: Unclaimed computer", "code": "unclaimed"})
            if request.get("expect") != expected:
                return self._reply({"ok": False, "error": "_Refused: Computer identity mismatch", "code": "identity"})
            if operation == "stage":
                self.staged[request["name"]] = base64.b64decode(request["data"])
                reply["value"] = {}
            elif operation == "rpc":
                reply["value"] = self.rpc_reply
        return self._reply(reply)

    @staticmethod
    def _reply(body):
        return {"response": io.BytesIO(json.dumps(body).encode())}

    def invoke_agent_runtime_command(self, **kwargs):
        self.commands.append(kwargs)
        if self.command_error is not None:
            raise self.command_error
        delta = {"stdout": self.command_stdout, "stderr": self.command_stderr}
        return {"stream": [{"chunk": {"contentDelta": delta}}, {"chunk": {"contentStop": self.command_reply}}]}

    def stop_runtime_session(self, **kwargs):
        self.stops.append(kwargs["runtimeSessionId"])
        self.retired.discard(kwargs["runtimeSessionId"])
        self.claims.pop(kwargs["runtimeSessionId"], None)
        self.incarnations.pop(kwargs["runtimeSessionId"], None)


def sandbox():
    value = AgentCoreSandbox(ARN, namespace="tests", lifetime=600)
    value._data = value._commands = Data()
    return value


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("agno.sandbox.agentcore.sandbox.time.sleep", lambda seconds: None)


# Provider


def test_constructor_validates_and_gives_commands_a_longer_read_timeout():
    for kwargs in ({"runtime_arn": "not-an-arn"}, {"runtime_arn": ARN, "lifetime": 10}):
        with pytest.raises(ValueError):
            AgentCoreSandbox(**kwargs)
    value = AgentCoreSandbox(ARN)
    assert value._commands is not value._data
    assert value._commands.meta.config.read_timeout > 3600 > value._data.meta.config.read_timeout


@pytest.mark.asyncio
async def test_create_is_idempotent_and_names_the_claim_incarnation():
    value = sandbox()
    first = await value.acreate("s", agent_id="a", env={"MODEL": "x"})
    second = await value.acreate("s", agent_id="a", env={"MODEL": "x"})
    assert first == second and first.provider_ref.startswith("agno-") and len(first.provider_ref) >= 33
    assert first.name == first.provider_ref + "/" + value._data.incarnations[first.provider_ref]
    claim = json.loads(value._data.invokes[0]["payload"])
    assert claim["env"] == {"MODEL": "x"} and claim["metadata"]["config"] == first.config_digest
    assert (await value.acreate("s", agent_id="a", generation=2)).provider_ref != first.provider_ref


@pytest.mark.asyncio
async def test_create_with_changed_configuration_is_refused():
    value = sandbox()
    await value.acreate("s", env={"MODEL": "x"})
    with pytest.raises(SandboxError, match="different configuration"):
        await value.acreate("s", env={"MODEL": "y"})


@pytest.mark.asyncio
async def test_a_stopped_generation_never_comes_back_through_this_provider():
    value = sandbox()
    handle = await value.acreate("s")
    await value.astop(handle)
    assert await value.aget(handle.provider_ref) is None
    with pytest.raises(SandboxError, match="new generation"):
        await value.acreate("s")


@pytest.mark.asyncio
async def test_unclaimed_replacement_compute_is_released_and_reported_gone():
    value = sandbox()
    reference = "agno-" + "f" * 40
    assert await value.aget(reference) is None
    assert value._data.stops == [reference]
    calls = len(value._data.invokes)
    assert await value.aget(reference) is None
    assert len(value._data.invokes) == calls


@pytest.mark.asyncio
async def test_find_returns_the_claimed_generation_and_refuses_changed_configuration():
    value = sandbox()
    handle = await value.acreate("s", agent_id="a", env={"MODEL": "x"})
    assert await value.afind("s", agent_id="a", env={"MODEL": "x"}) == handle
    with pytest.raises(SandboxError, match="different compute configuration"):
        await value.afind("s", agent_id="a", env={"MODEL": "y"})
    await value.astop(handle)
    calls = len(value._data.invokes)
    assert await value.afind("s", agent_id="a", env={"MODEL": "x"}) is None
    assert len(value._data.invokes) == calls


@pytest.mark.asyncio
async def test_find_leaves_a_fresh_microvm_for_the_create_that_follows():
    value = sandbox()
    assert await value.afind("s", for_create=True) is None
    handle = await value.acreate("s")
    assert value._data.stops == []
    sessions = {call["runtimeSessionId"] for call in value._data.invokes}
    assert sessions == {handle.provider_ref}


@pytest.mark.asyncio
async def test_find_stops_the_microvm_it_started_when_no_create_follows():
    value = sandbox()
    name = value._name("s", None, 1)
    assert await value.afind("s") is None
    assert value._data.stops == [name]
    # Never claimed, so nothing guards it and a later create may still claim it.
    assert name not in value._stopped and name not in value._session_locks
    assert (await value.acreate("s")).provider_ref == name


@pytest.mark.asyncio
async def test_stop_records_are_dropped_after_a_lifetime(monkeypatch):
    value = sandbox()
    clock = [1000.0]
    monkeypatch.setattr(agentcore_sandbox.time, "monotonic", lambda: clock[0])
    old = await value.acreate("s", generation=1)
    await value.astop(old)
    clock[0] += value.lifetime
    new = await value.acreate("s", generation=2)
    await value.astop(new)
    assert list(value._stopped) == [new.provider_ref]
    assert old.provider_ref not in value._session_locks


@pytest.mark.asyncio
async def test_find_replaces_a_retired_microvm_so_the_generation_can_still_be_created():
    value = sandbox()
    name = value._name("s", None, 1)
    value._data.retired.add(name)
    assert await value.afind("s") is None
    assert value._data.stops == [name]
    assert (await value.acreate("s")).provider_ref == name


@pytest.mark.asyncio
async def test_a_handle_never_runs_on_a_later_claim_of_its_session():
    value = sandbox()
    handle = await value.acreate("s")
    # The microVM ended and another create claimed a fresh one for the same session.
    value._data.incarnations[handle.provider_ref] = "later"
    # The computer refuses the staging upload, which names the handle's incarnation.
    with pytest.raises(SandboxError, match="identity mismatch"):
        await value.aexec(handle, ["true"])
    with pytest.raises(SandboxError, match="identity mismatch"):
        await value.arpc(handle, "poll", b"{}")
    assert value._data.commands == [] and value._data.stops == []


@pytest.mark.asyncio
async def test_exec_stages_stdin_for_the_named_computer_and_runs_through_the_guard():
    value = sandbox()
    handle = await value.acreate("s")
    result = await value.aexec(handle, ["cat"], stdin=b"input", timeout=5)
    assert result.stdout == "hi"
    command = value._data.commands[0]["body"]["command"]
    expect = value._expect(handle)
    assert command.startswith(
        f"python -I -m agno.sandbox.agentcore.server exec --expect {expect['config']}:{expect['incarnation']} --stdin "
    )
    # The guard starts the runner itself, so the command names no other program.
    assert command.split()[-2] == "--stdin"
    ((name, staged),) = value._data.staged.items()
    assert name in command and json.loads(staged)["argv"] == ["cat"]
    assert value._data.commands[0]["body"]["timeout"] == 20


@pytest.mark.asyncio
async def test_guard_refusals_count_only_when_the_guard_recorded_them():
    value = sandbox()
    handle = await value.acreate("s")
    value._data.command_reply = {"exitCode": 125, "status": "COMPLETED"}
    value._data.command_stderr = "AgentCore computer refusing to run [unusable]: _Refused: reached its lifetime\n"
    value._data.refusal_code = "unusable"
    with pytest.raises(SandboxError, match="refused the command"):
        await value.aexec(handle, ["true"])
    assert value._data.stops == []
    # The same output from code that ran after the privilege drop is not a refusal.
    value._data.refusal_code = None
    with pytest.raises(SandboxError, match="transport failed"):
        await value.aexec(handle, ["true"])
    assert value._data.stops == [handle.provider_ref]
    value = sandbox()
    handle = await value.acreate("s")
    value._data.command_reply = {"exitCode": 125, "status": "COMPLETED"}
    value._data.command_stderr = "AgentCore computer refusing to run [unclaimed]: _Refused: Unclaimed computer\n"
    value._data.refusal_code = "unclaimed"
    with pytest.raises(SandboxError, match="refused the command"):
        await value.aexec(handle, ["true"])
    assert value._data.stops == [handle.provider_ref]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        client_error("ThrottlingException"),
        client_error("AccessDeniedException"),
        EndpointConnectionError(endpoint_url="https://bedrock-agentcore.us-east-1.amazonaws.com"),
    ],
)
async def test_commands_refused_before_sending_leave_compute_running(no_sleep, error):
    value = sandbox()
    handle = await value.acreate("s")
    value._data.command_error = error
    with pytest.raises(type(error)):
        await value.aexec(handle, ["true"])
    assert value._data.stops == []


@pytest.mark.asyncio
async def test_uncertain_commands_stop_compute_and_are_never_resent(no_sleep):
    value = sandbox()
    handle = await value.acreate("s")
    value._data.command_error = client_error("502")
    with pytest.raises(ClientError):
        await value.aexec(handle, ["true"])
    assert len(value._data.commands) == 1 and value._data.stops == [handle.provider_ref]
    value = sandbox()
    handle = await value.acreate("s")
    value._data.command_reply = {"exitCode": -1, "status": "TIMED_OUT"}
    with pytest.raises(SandboxError, match="transport failed"):
        await value.aexec(handle, ["sleep", "9"], timeout=1)
    assert value._data.stops == [handle.provider_ref]


@pytest.mark.asyncio
async def test_rpc_failures_never_touch_the_claimed_computer():
    value = sandbox()
    handle = await value.acreate("s")
    assert (await value.arpc(handle, "poll", b'{"wait": 10}')).stdout == '{"version": 1}'
    value._data.rpc_reply = {"status": 500, "body": "boom"}
    failed = await value.arpc(handle, "poll", b"{}")
    assert failed.exit_code == 1 and failed.stderr == "boom" and value._data.stops == []
    with pytest.raises(ValueError):
        await value.arpc(handle, "exec", b"{}")
    # Text from the runtime server cannot pose as the server's own refusal.
    value._data.rpc_reply = {"status": 502, "body": "Unclaimed computer"}
    assert (await value.arpc(handle, "poll", b"{}")).stderr == "Unclaimed computer"
    assert value._data.stops == []
    # The microVM ended: the call reached an unclaimed replacement, which is released.
    value._data.claims.pop(handle.provider_ref)
    with pytest.raises(SandboxError, match="microVM ended"):
        await value.arpc(handle, "poll", b"{}")
    assert value._data.stops == [handle.provider_ref]


@pytest.mark.asyncio
async def test_rejections_before_execution_are_retried_and_others_are_not(no_sleep):
    value = sandbox()
    value._data.conflicts = 2
    await value.acreate("s")
    assert len(value._data.invokes) == 3
    value._data.conflict_code, value._data.conflicts = "ThrottlingException", 3
    await value.acreate("s")
    assert len(value._data.invokes) == 7
    value._data.conflict_code, value._data.conflicts = "502", 1
    await value.acreate("s")
    assert len(value._data.invokes) == 9
    value._data.conflict_code, value._data.conflicts = "ValidationException", 1
    with pytest.raises(ClientError):
        await value.acreate("s")


@pytest.mark.asyncio
async def test_oversized_command_input_is_refused_before_anything_is_sent():
    value = sandbox()
    handle = await value.acreate("s")
    sent = len(value._data.invokes)
    with pytest.raises(ValueError, match="staged request limit"):
        await value.aexec(handle, ["echo", "x" * (12 * 1024 * 1024)])
    assert len(value._data.invokes) == sent and value._data.commands == [] and value._data.stops == []


@pytest.mark.asyncio
async def test_failed_staging_leaves_compute_running():
    value = sandbox()
    handle = await value.acreate("s")
    invoke = value._invoke

    def refuse_stage(reference, operation, **payload):
        if operation == "stage":
            raise SandboxError("AgentCore sandbox refused stage: upload failed")
        return invoke(reference, operation, **payload)

    value._invoke = refuse_stage
    with pytest.raises(SandboxError, match="upload failed"):
        await value.aexec(handle, ["true"])
    assert value._data.commands == [] and value._data.stops == []


@pytest.mark.asyncio
async def test_pause_is_not_supported():
    value = sandbox()
    handle = await value.acreate("s")
    with pytest.raises(NotImplementedError):
        await value.apause(handle)


# In-computer server


def socket_row(local, remote, uid, state="01"):
    def encode(address):
        host, port = address
        return bytes(int(part) for part in host.split("."))[::-1].hex().upper() + ":%04X" % port

    return f"0: {encode(local)} {encode(remote)} {state} 0:0 0:0 0 {uid} 0 1"


def test_only_established_forwarder_connections_over_loopback_are_trusted(monkeypatch):
    rows = [
        socket_row(("127.0.0.1", 40001), ("127.0.0.1", 8080), 993),
        socket_row(("127.0.0.1", 40002), ("127.0.0.1", 8080), 0),
        socket_row(("127.0.0.1", 40003), ("127.0.0.1", 8080), 1000),
        socket_row(("10.0.0.5", 40004), ("10.0.0.5", 8080), 993),
        # A client that already closed its end: the kernel reports UID 0 for it.
        socket_row(("127.0.0.1", 40005), ("127.0.0.1", 8080), 0, state="05"),
    ]
    monkeypatch.setattr(server, "_socket_table", lambda: rows)
    assert server._trusted(("127.0.0.1", 40001)) and server._trusted(("127.0.0.1", 40002))
    assert not server._trusted(("127.0.0.1", 40003))
    assert not server._trusted(("127.0.0.1", 40005))
    # Loopback with no matching socket, any non-loopback peer, and an unreadable table fail closed.
    assert not server._trusted(("127.0.0.1", 40009))
    assert not server._trusted(("10.0.0.5", 40004)) and not server._trusted(("172.16.0.9", 40001))
    monkeypatch.setattr(server, "_socket_table", lambda: [])
    assert not server._trusted(("127.0.0.1", 40001))


@pytest.fixture
def computer(tmp_path, monkeypatch):
    """The real server operations on temporary directories, as this test's user."""
    control, workspace, runtime = tmp_path / "control", tmp_path / "workspace", tmp_path / "runtime"
    storage = tmp_path / "storage"
    control.mkdir(mode=0o700)
    storage.mkdir()
    monkeypatch.setattr(server, "_storage_mounted", lambda: storage.is_dir())
    for name, value in (
        ("_STORAGE", storage),
        ("_CONTROL", control),
        ("_CLAIM", control / "claim.json"),
        ("_WORKSPACE", workspace),
        ("_RUNTIME", runtime),
        ("_ROOTS", {"workspace": workspace, "native": runtime / "native"}),
        ("_USER", os.getuid()),
        ("_GROUP", os.getgid()),
        # Children inherit PYTHONPATH so they import this checkout.
        ("_PYTHON", [sys.executable]),
        ("_state", {"token": None, "supervisor": None, "timer": None, "unhealthy": 0, "importing": False}),
    ):
        monkeypatch.setattr(server, name, value)
    # Children start in / and must import this checkout, not an installed agno.
    monkeypatch.setenv("PYTHONPATH", str(Path(server.__file__).resolve().parents[3]))
    # Freezing this user's processes would stop the test runner itself.
    monkeypatch.setattr(server, "_freeze", lambda: [])
    monkeypatch.setattr(server, "_control_dir", lambda: None)
    monkeypatch.setattr(server, "_start_timer", lambda deadline: None)
    monkeypatch.setattr(server, "_start_runtime", lambda claim: server._state.update(token="t"))
    monkeypatch.setattr(server, "_runtime_healthy", lambda: True)
    value = sandbox()

    def invoke(reference, operation, **payload):
        payload.pop("idempotent", None)
        payload.pop("slow", None)
        try:
            return server._OPERATIONS[operation](payload)
        except Exception as error:
            # The real server answers errors in the body, which _invoke raises as
            # SandboxError, or as a refusal carrying its code.
            message = f"AgentCore sandbox refused {operation}: {type(error).__name__}: {error}"
            if isinstance(error, server._Refused):
                raise _Refusal(message, error.code) from error
            raise SandboxError(message) from error

    value._invoke = invoke

    def replace_microvm():
        # AgentCore starts a blank microVM: nothing of the old one survives, except
        # the session storage mount, which outlives a stop.
        for path in (control, workspace, runtime):
            shutil.rmtree(path, ignore_errors=True)
        control.mkdir(mode=0o700)
        server._state.update(token=None, supervisor=None)

    return SimpleNamespace(
        sandbox=value,
        control=control,
        workspace=workspace,
        native=runtime / "native",
        storage=storage,
        replace=replace_microvm,
    )


@pytest.mark.asyncio
async def test_largest_allowed_stdin_is_accepted_by_the_server(computer):
    handle = await computer.sandbox.acreate("s")
    stdin = os.urandom(8 * 1024 * 1024)
    assert (await computer.sandbox.aexec(handle, ["cat"], stdin=stdin)).exit_code == 0
    (staged,) = computer.control.glob("*.stdin")
    assert 8 * 1024 * 1024 < staged.stat().st_size <= server._MAX_STAGED
    assert base64.b64decode(json.loads(staged.read_bytes())["stdin"]) == stdin


@pytest.mark.asyncio
async def test_checkpoint_round_trip_into_a_replacement_microvm(computer, tmp_path, monkeypatch):
    monkeypatch.setattr("agno.sandbox.agentcore.transfer._CHUNK", 4096)
    handle = await computer.sandbox.acreate("s")
    (computer.workspace / "src").mkdir()
    (computer.workspace / "src" / "app.py").write_text("print('hi')\n" * 4000)
    (computer.workspace / "link").symlink_to("src/app.py")
    (computer.workspace / ".venv" / "bin").mkdir(parents=True)
    (computer.workspace / ".venv" / "bin" / "python3").symlink_to("/usr/local/bin/python3")
    computer.native.mkdir(mode=0o700)
    (computer.native / "transcript.jsonl").write_text('{"turn": 1}\n')
    (computer.native / "codex" / ".tmp" / "plugins").mkdir(parents=True)
    (computer.native / "codex" / ".tmp" / "plugins" / "clone.bin").write_bytes(b"x" * 5000)
    (computer.native / "codex" / ".tmp" / "marketplaces").mkdir()
    (computer.native / "codex" / "auth.json").write_text("secret")

    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    reference = await transfer.acapture(handle, state={"turn": 1})
    assert not list(computer.control.glob("*.checkpoint"))

    computer.replace()
    replacement = await computer.sandbox.acreate("s", generation=2)
    assert await transfer.arestore(replacement, reference) == {"turn": 1}
    assert (computer.workspace / "src" / "app.py").read_text() == "print('hi')\n" * 4000
    assert os.readlink(computer.workspace / "link") == "src/app.py"
    assert os.readlink(computer.workspace / ".venv" / "bin" / "python3") == "/usr/local/bin/python3"
    assert (computer.native / "transcript.jsonl").read_text() == '{"turn": 1}\n'
    assert (computer.native / "codex" / ".tmp" / "marketplaces").is_dir()
    assert not (computer.native / "codex" / "auth.json").exists()
    assert not (computer.native / "codex" / ".tmp" / "plugins").exists()
    assert not list(computer.control.glob("*.checkpoint"))
    # A restored generation has been used, so it never takes a second restore.
    with pytest.raises(SandboxError, match="empty, unused"):
        await transfer.arestore(replacement, reference)


@pytest.mark.asyncio
async def test_capture_refuses_a_hardlink_alias_of_an_excluded_credential(computer, tmp_path):
    handle = await computer.sandbox.acreate("s")
    (computer.native / "codex").mkdir(parents=True)
    (computer.native / "codex" / "auth.json").write_text("secret")
    os.link(computer.native / "codex" / "auth.json", computer.native / "aaa")
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    with pytest.raises(SandboxError, match="hardlink to excluded"):
        await transfer.acapture(handle, state={})


@pytest.mark.asyncio
async def test_capture_refuses_a_symlinked_root(computer, tmp_path):
    handle = await computer.sandbox.acreate("s")
    outside = tmp_path / "outside"
    outside.mkdir()
    computer.native.symlink_to(outside)
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    with pytest.raises(SandboxError, match="real directories"):
        await transfer.acapture(handle, state={})


@pytest.mark.asyncio
async def test_a_failed_restore_stops_the_computer_and_it_refuses_all_work(computer, tmp_path):
    handle = await computer.sandbox.acreate("s")
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    reference = await transfer.acapture(handle, state={})
    computer.replace()
    replacement = await computer.sandbox.acreate("s", generation=2)
    computer.workspace.joinpath("left-over").write_text("x")
    with pytest.raises(SandboxError, match="empty, unused"):
        await transfer.arestore(replacement, reference)
    assert computer.sandbox._data.stops == [replacement.provider_ref]
    with pytest.raises(PermissionError, match="must be replaced"):
        server._stage({"expect": computer.sandbox._expect(replacement), "name": "a" * 32, "data": ""})


def test_requests_must_name_the_claimed_incarnation(computer):
    claim = server._claim({"metadata": {"config": "c"}, "env": {}, "lifetime": 600})
    good = {"config": "c", "incarnation": claim["incarnation"]}
    assert server._require({"expect": good})
    for expect in (None, {"config": "c", "incarnation": "other"}, {"config": "d", "incarnation": claim["incarnation"]}):
        with pytest.raises(PermissionError, match="identity mismatch"):
            server._require({"expect": expect})


def test_a_runtime_that_never_starts_leaves_the_computer_unclaimed(computer, monkeypatch):
    stops = []

    def failing(claim):
        raise RuntimeError("The sandbox runtime server did not become ready")

    monkeypatch.setattr(server, "_start_runtime", failing)
    monkeypatch.setattr(server, "_stop_runtime", lambda: stops.append(1))
    with pytest.raises(RuntimeError, match="did not become ready"):
        server._claim({"metadata": {"config": "c"}, "env": {}, "lifetime": 600})
    assert not (computer.control / "claim.json").exists() and stops == [1]


def test_a_repeated_claim_restarts_the_runtime_only_after_repeated_misses(computer, monkeypatch):
    starts, health = [], {"ok": True}
    monkeypatch.setattr(server, "_start_runtime", lambda claim: starts.append(1))
    monkeypatch.setattr(server, "_stop_runtime", lambda: None)
    monkeypatch.setattr(server, "_runtime_healthy", lambda: health["ok"])
    request = {"metadata": {"config": "c"}, "env": {}, "lifetime": 600}
    first = server._claim(request)
    assert first["created"] is True and len(starts) == 1
    assert server._claim(request) == {**first, "created": False}
    health["ok"] = False
    server._claim(request)
    server._claim(request)
    assert len(starts) == 1
    server._claim(request)
    assert len(starts) == 2


def test_lifetime_and_failure_markers_refuse_work(computer):
    claim = server._claim({"metadata": {"config": "c"}, "env": {}, "lifetime": 600})
    expect = {"config": "c", "incarnation": claim["incarnation"]}
    claim_file = computer.control / "claim.json"
    expired = json.loads(claim_file.read_text())
    expired["deadline"] = 0
    claim_file.write_text(json.dumps(expired))
    with pytest.raises(PermissionError, match="lifetime"):
        server._require({"expect": expect})


def test_ping_reads_agent_files_without_following_links(computer):
    jobs = computer.native.parent / "jobs" / "job"
    jobs.mkdir(parents=True)
    (jobs / "status.json").symlink_to("/dev/zero")
    assert server._busy() is False


@pytest.mark.asyncio
async def test_a_stop_is_recorded_even_when_its_reply_is_lost():
    value = sandbox()
    handle = await value.acreate("s")

    def lost(**kwargs):
        raise client_error("502")

    value._data.stop_runtime_session = lost
    with pytest.raises(ClientError):
        await value.astop(handle)
    with pytest.raises(SandboxError, match="new generation"):
        await value.acreate("s")


def test_capture_rejects_an_archive_whose_exclusions_were_tampered_with(computer, tmp_path):
    from agno.sandbox.checkpoint import CheckpointArchive

    (computer.native / "codex").mkdir(parents=True)
    (computer.native / "codex" / "auth.json").write_text("secret")
    computer.workspace.mkdir()
    tampered = tmp_path / "tampered.tar"
    # An archive built without the exclusions, as a replaced capture output would be.
    CheckpointArchive().capture({"workspace": computer.workspace, "native": computer.native}, tampered, state={})
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    with pytest.raises(SandboxError, match="requested exclusions"):
        transfer._check_excluded(tampered, ["native/codex/auth.json"])


@pytest.mark.asyncio
async def test_restore_moves_entries_out_of_a_read_only_archived_root(computer, tmp_path):
    handle = await computer.sandbox.acreate("s")
    computer.native.mkdir()
    (computer.native / "state.json").write_text("{}")
    computer.native.chmod(0o555)
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    reference = await transfer.acapture(handle, state={})
    computer.native.chmod(0o700)
    computer.replace()
    replacement = await computer.sandbox.acreate("s", generation=2)
    await transfer.arestore(replacement, reference)
    assert (computer.native / "state.json").read_text() == "{}"
    assert computer.native.stat().st_mode & 0o777 == 0o700


def test_work_refuses_during_a_capture(computer):
    server._claim({"metadata": {"config": "c"}, "env": {}, "lifetime": 600})
    claim = server._load_claim()
    server._mark(server._CAPTURING)
    with pytest.raises(PermissionError, match="capture is in progress"):
        server._begin_work(claim)
    (computer.control / server._CAPTURING).unlink()
    server._begin_work(claim)
    assert server._marked(server._USED)


def test_an_interrupted_restore_makes_the_computer_unusable(computer):
    request = {"metadata": {"config": "c"}, "env": {}, "lifetime": 600}
    server._claim(request)
    server._mark(server._RESTORING)
    with pytest.raises(PermissionError, match="must be replaced"):
        server._claim(request)


def test_an_unclaimed_microvm_that_answers_a_handle_is_retired(computer):
    with pytest.raises(PermissionError, match="Unclaimed"):
        server._require({"expect": {"config": "c", "incarnation": "i"}})
    # A create racing the provider's stop of this replacement cannot claim it.
    with pytest.raises(PermissionError, match="retired"):
        server._claim({"metadata": {"config": "c"}, "env": {}, "lifetime": 600})


def test_peek_leaves_an_unclaimed_microvm_claimable(computer):
    assert server._peek({}) == {"claimed": False, "retired": False}
    claim = server._claim({"metadata": {"config": "c"}, "env": {}, "lifetime": 600})
    assert server._peek({}) == {"claimed": True, "metadata": {"config": "c"}, "incarnation": claim["incarnation"]}


def test_peek_reports_a_retired_microvm(computer):
    with pytest.raises(PermissionError, match="Unclaimed"):
        server._require({"expect": {"config": "c", "incarnation": "i"}})
    assert server._peek({}) == {"claimed": False, "retired": True}


def test_capture_rejects_data_after_the_end_of_the_archive(computer, tmp_path):
    from agno.sandbox.checkpoint import CheckpointArchive

    computer.workspace.mkdir()
    computer.native.mkdir(parents=True)
    exclude = ["native/codex/auth.json"]
    archive = tmp_path / "archive.tar"
    CheckpointArchive(compress=False).capture(
        {"workspace": computer.workspace, "native": computer.native}, archive, state={}, exclude=exclude
    )
    transfer = AgentCoreCheckpointTransfer(
        computer.sandbox, FileCheckpointStore(tmp_path / "store"), archive=CheckpointArchive(compress=False)
    )
    transfer._check_excluded(archive, exclude)
    with archive.open("ab") as stream:
        stream.write(b"native/codex/auth.json secret")
    with pytest.raises(SandboxError, match="after the end of the archive"):
        transfer._check_excluded(archive, exclude)


def test_a_handle_arriving_during_a_first_claim_waits_instead_of_retiring(computer):
    server._mark(server._CLAIMING)
    with pytest.raises(PermissionError, match="claim is in progress"):
        server._require({"expect": {"config": "c", "incarnation": "i"}})
    assert not server._marked(server._FAILED)


def test_a_repeated_claim_is_answered_while_the_server_lock_is_held(computer):
    request = {"metadata": {"config": "c"}, "env": {}, "lifetime": 600}
    first = server._claim(request)
    with server._lock:
        again = server._claim(request)
    assert again["incarnation"] == first["incarnation"] and again["created"] is False


def test_a_repeated_claim_leaves_the_runtime_alone_during_a_capture(computer, monkeypatch):
    request = {"metadata": {"config": "c"}, "env": {}, "lifetime": 600}
    server._claim(request)
    checks = []
    monkeypatch.setattr(server, "_runtime_healthy", lambda: checks.append(1) or False)
    server._mark(server._CAPTURING)
    for _ in range(4):
        server._claim(request)
    assert checks == []


def test_a_transfer_child_that_overruns_is_killed(monkeypatch):
    monkeypatch.setattr(server, "_CHILD_TIMEOUT", 0.2)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.PIPE)
    with pytest.raises(ValueError, match="time limit"):
        server._finish(child, b"")
    assert child.returncode is not None


def test_freeze_skips_processes_the_agent_already_stopped(monkeypatch):
    signals = []
    monkeypatch.setattr(server, "_agent_pids", lambda: [10, 11])
    monkeypatch.setattr(server, "_process_state", lambda pid: "T" if pid == 10 else "S")
    monkeypatch.setattr(server.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert server._freeze() == [11]
    assert signals == [(11, signal.SIGSTOP)]


def test_process_state_reads_past_a_command_name_with_spaces_and_parentheses(monkeypatch, tmp_path):
    stat = "42 (bad ) name) T 1 42 42 0 -1"
    # Every pid maps into tmp_path, so a real process on a Linux host never answers.
    monkeypatch.setattr(server, "Path", lambda path: tmp_path / path.replace("/", "_"))
    (tmp_path / "_proc_42_stat").write_text(stat)
    assert server._process_state(42) == "T"
    assert server._process_state(43) == ""


def test_transfer_objects_are_removed_on_a_failed_computer(computer):
    server._mark(server._FAILED)
    name = "a" * 32
    server._transfer_file(name).write_bytes(b"x")
    server._remove({"name": name})
    assert not server._transfer_file(name).exists()


def test_the_runtime_server_is_never_followed_through_a_redirect(monkeypatch):
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(server, "_RUNTIME_PORT", httpd.server_address[1])
        monkeypatch.setitem(server._state, "token", "t")
        status, _ = server._forward("GET", "/health", None, timeout=5)
        assert status == 302
    finally:
        httpd.shutdown()


def test_checkpoint_limits_above_what_agentcore_moves_are_refused(tmp_path):
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

    archive = CheckpointArchive(limits=CheckpointLimits(max_bytes=3 * 1024 * 1024 * 1024))
    with pytest.raises(ValueError, match="2 GiB"):
        AgentCoreCheckpointTransfer(sandbox(), FileCheckpointStore(tmp_path), archive=archive)


@pytest.mark.asyncio
async def test_a_stale_handle_restoring_never_stops_the_current_computer(computer, tmp_path):
    handle = await computer.sandbox.acreate("s")
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    reference = await transfer.acapture(handle, state={})
    # A handle for an earlier claim of the same session names another incarnation.
    stale = dataclasses.replace(handle, name=handle.provider_ref + "/earlier")
    with pytest.raises(SandboxError, match="identity mismatch"):
        await transfer.arestore(stale, reference)
    assert computer.sandbox._data.stops == []


@pytest.mark.asyncio
async def test_a_checkpoint_that_cannot_be_read_leaves_the_computer_running(tmp_path):
    value = sandbox()
    handle = await value.acreate("s")
    transfer = AgentCoreCheckpointTransfer(value, FileCheckpointStore(tmp_path))
    missing = CheckpointRef(sha256="0" * 64, size=1)
    with pytest.raises(Exception):
        await transfer.arestore(handle, missing)
    assert value._data.stops == []


def test_the_server_runs_as_a_module_without_loading_the_provider():
    # The image starts the server with -m, which imports its package first. The
    # package must not import the provider, or the server would load twice and
    # warn on every guarded command.
    env = dict(os.environ, PYTHONPATH=str(Path(server.__file__).resolve().parents[3]))
    code = "import sys, agno.sandbox.agentcore; print('agno.sandbox.agentcore.sandbox' in sys.modules)"
    imported = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    assert imported.stdout == "False\n"
    usage = subprocess.run(
        [sys.executable, "-W", "error", "-m", "agno.sandbox.agentcore.server"], capture_output=True, text=True, env=env
    )
    assert usage.returncode == 1 and usage.stderr.startswith("usage: ")


@pytest.mark.asyncio
async def test_a_repeated_claim_racing_a_restore_never_fails_the_computer(computer, tmp_path, monkeypatch):
    handle = await computer.sandbox.acreate("s")
    computer.native.mkdir(mode=0o700)
    (computer.native / "transcript.jsonl").write_text('{"turn": 1}\n')
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    reference = await transfer.acapture(handle, state={"turn": 1})
    computer.replace()
    replacement = await computer.sandbox.acreate("s", generation=2)

    # A repeated create lands the moment the import releases the lifecycle lock,
    # after it marked the computer restoring.
    lifecycle, raced = server._lifecycle, []

    @contextmanager
    def racing():
        with lifecycle():
            yield
        if server._marked(server._RESTORING) and not raced:
            raced.append(True)
            claim = server._load_claim()
            server._claim({"metadata": claim["metadata"], "env": claim["env"], "lifetime": 600})

    monkeypatch.setattr(server, "_lifecycle", racing)
    assert await transfer.arestore(replacement, reference) == {"turn": 1}
    assert raced and not server._marked(server._FAILED)


# Session storage


async def _captured(computer, tmp_path, state=None):
    handle = await computer.sandbox.acreate("s")
    computer.workspace.joinpath("app.py").write_text("print('hi')\n")
    computer.native.mkdir(mode=0o700, exist_ok=True)
    computer.native.joinpath("transcript.jsonl").write_text('{"turn": 1}\n')
    transfer = AgentCoreCheckpointTransfer(computer.sandbox, FileCheckpointStore(tmp_path / "store"))
    reference = await transfer.acapture(handle, state=state or {"turn": 1})
    return handle, transfer, reference


def stop_replaces_the_microvm(computer):
    # A stop ends the microVM; the next call to the session starts a blank one.
    data = computer.sandbox._data
    original = data.stop_runtime_session

    def stop(**kwargs):
        original(**kwargs)
        computer.replace()

    data.stop_runtime_session = stop


@pytest.mark.asyncio
async def test_a_capture_keeps_its_archive_on_session_storage(computer, tmp_path):
    _, _, reference = await _captured(computer, tmp_path)
    kept = computer.storage / server._KEPT
    assert kept.stat().st_size == reference.size
    assert hashlib.sha256(kept.read_bytes()).hexdigest() == reference.sha256
    assert [path.name for path in computer.storage.iterdir()] == [server._KEPT]


@pytest.mark.asyncio
async def test_resume_restores_the_kept_checkpoint_on_a_replacement_microvm(computer, tmp_path):
    handle, transfer, reference = await _captured(computer, tmp_path)
    stop_replaces_the_microvm(computer)
    await computer.sandbox.astop(handle)

    resumed, state = await transfer.aresume("s", reference)
    assert state == {"turn": 1}
    assert (resumed.provider_ref, resumed.generation) == (handle.provider_ref, handle.generation)
    assert resumed.name != handle.name
    assert computer.workspace.joinpath("app.py").read_text() == "print('hi')\n"
    assert computer.native.joinpath("transcript.jsonl").read_text() == '{"turn": 1}\n'
    assert not list(computer.control.glob("*.checkpoint"))
    # The resumed computer works for its new handle and never for the old one.
    assert server._require({"expect": computer.sandbox._expect(resumed)})
    with pytest.raises(PermissionError, match="identity mismatch"):
        server._require({"expect": computer.sandbox._expect(handle)})
    # A resumed generation is used, so it never takes a restore on top.
    with pytest.raises(SandboxError, match="empty, unused"):
        await transfer.arestore(resumed, reference)


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["tamper", "delete", "replace with a link", "stale"])
async def test_resume_refuses_a_copy_that_does_not_match_the_reference(computer, tmp_path, damage):
    handle, transfer, reference = await _captured(computer, tmp_path)
    kept = computer.storage / server._KEPT
    if damage == "tamper":
        data = bytearray(kept.read_bytes())
        data[len(data) // 2] ^= 1
        kept.write_bytes(bytes(data))
    elif damage == "delete":
        kept.unlink()
    elif damage == "replace with a link":
        (tmp_path / "elsewhere").write_bytes(kept.read_bytes())
        kept.unlink()
        kept.symlink_to(tmp_path / "elsewhere")
    else:
        # A later capture replaced the copy; the earlier reference no longer matches.
        await transfer.acapture(handle, state={"turn": 2})
    await computer.sandbox.astop(handle)
    # Replaced by hand, so the stop after the failed resume leaves its leftovers visible.
    computer.replace()

    with pytest.raises(SandboxError, match="session storage"):
        await transfer.aresume("s", reference)
    # Nothing was claimed, and the microVM the resume reached is stopped.
    assert server._load_claim() is None
    assert computer.sandbox._data.stops == [handle.provider_ref] * 2
    assert not list(computer.control.glob("*.checkpoint"))


@pytest.mark.asyncio
async def test_a_resume_whose_runtime_never_starts_leaves_nothing_behind(computer, tmp_path, monkeypatch):
    handle, transfer, reference = await _captured(computer, tmp_path)
    await computer.sandbox.astop(handle)
    computer.replace()

    def never_starts(claim):
        raise RuntimeError("The sandbox runtime server did not become ready")

    monkeypatch.setattr(server, "_start_runtime", never_starts)
    with pytest.raises(SandboxError, match="did not become ready"):
        await transfer.aresume("s", reference)
    assert server._load_claim() is None
    assert computer.sandbox._data.stops == [handle.provider_ref] * 2
    assert not list(computer.control.glob("*.checkpoint"))


@pytest.mark.asyncio
async def test_resume_never_touches_a_generation_that_is_still_running(computer, tmp_path):
    handle, transfer, reference = await _captured(computer, tmp_path)
    with pytest.raises(SandboxError, match="still running"):
        await transfer.aresume("s", reference)
    assert computer.sandbox._data.stops == []
    assert server._require({"expect": computer.sandbox._expect(handle)})


@pytest.mark.asyncio
async def test_resume_replaces_a_retired_microvm_and_tries_once_more(computer, tmp_path):
    handle, transfer, reference = await _captured(computer, tmp_path)
    computer.replace()
    # A lookup reached the replacement first and retired it.
    assert server._describe({}) == {"claimed": False}
    stop_replaces_the_microvm(computer)

    resumed, state = await transfer.aresume("s", reference)
    assert state == {"turn": 1}
    assert computer.sandbox._data.stops == [handle.provider_ref]
    assert server._require({"expect": computer.sandbox._expect(resumed)})


@pytest.mark.asyncio
async def test_without_session_storage_capture_works_and_resume_is_refused(computer, tmp_path):
    shutil.rmtree(computer.storage)
    handle, transfer, reference = await _captured(computer, tmp_path)
    stop_replaces_the_microvm(computer)
    await computer.sandbox.astop(handle)
    with pytest.raises(SandboxError, match="session storage"):
        await transfer.aresume("s", reference)


@pytest.mark.asyncio
async def test_a_copy_that_cannot_be_kept_never_fails_the_capture(computer, tmp_path):
    computer.storage.chmod(0o500)
    try:
        _, _, reference = await _captured(computer, tmp_path)
    finally:
        computer.storage.chmod(0o700)
    assert reference.size > 0
    assert list(computer.storage.iterdir()) == []


@pytest.mark.asyncio
async def test_resume_keeps_the_generation_configuration(computer, tmp_path):
    handle, transfer, reference = await _captured(computer, tmp_path)
    stop_replaces_the_microvm(computer)
    await computer.sandbox.astop(handle)
    resumed, _ = await transfer.aresume("s", reference)
    assert resumed.config_digest == handle.config_digest
    with pytest.raises(SandboxError, match="different configuration"):
        await computer.sandbox.acreate("s", env={"CHANGED": "1"})
