"""Agent 37 sandbox contracts against a fake REST API that runs the real in-instance script."""

import base64
import hashlib
import io
import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path

import httpx
import pytest

import agno.sandbox.agent37.sandbox as agent37_sandbox
from agno.sandbox.agent37 import Agent37CheckpointTransfer, Agent37Sandbox, _guest
from agno.sandbox.base import SandboxError, SandboxHandle
from agno.sandbox.checkpoint import CheckpointObjectNotFound, CheckpointRef, FileCheckpointStore
from agno.sandbox.pool import LoopClients
from agno.sandbox.transfer import REMOTE_NATIVE_EXCLUSIONS, CheckpointTransfer

KEY = "sk_test_key"
GUEST = Path(_guest.__file__).read_text()


class Service:
    """Answers like Agent 37: the instances API on one host, exec on the other."""

    def __init__(self, root):
        self.root = root
        self.instances = {}
        self.requests = []
        self.runs = {}
        self.executed = []
        self.injected = []
        self.on_create = None
        self.clock = 0

    def add(self, body, status="running"):
        self.clock += 1
        ident = f"inst{self.clock:06d}"
        self.instances[ident] = {
            "id": ident,
            "status": status,
            "template": body.get("template"),
            "name": body.get("name"),
            "metadata": body.get("metadata"),
            "created": self.clock,
            "url": f"https://{ident}.agent37.app",
        }
        return self.instances[ident]

    def inject(self, method, suffix, outcome, *, times=1, after=False, skip=0):
        """Answer the next matching requests with ``outcome``, after letting ``skip`` of them through;
        ``after`` does the work first, as a lost reply."""
        self.injected.append(
            {"method": method, "suffix": suffix, "outcome": outcome, "times": times, "after": after, "skip": skip}
        )

    def sent(self, method, suffix):
        return [item for item in self.requests if item[0] == method and item[2].endswith(suffix)]

    async def handle(self, request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.host, request.url.path, body))
        for item in self.injected:
            if item["times"] and item["method"] == request.method and request.url.path.endswith(item["suffix"]):
                if item["skip"]:
                    item["skip"] -= 1
                    continue
                item["times"] -= 1
                if item["after"]:
                    self.answer(request, body)
                if isinstance(item["outcome"], Exception):
                    raise item["outcome"]
                return item["outcome"]
        return self.answer(request, body)

    def answer(self, request, body):
        parts = request.url.path.split("/")[2:]
        if request.url.host == "sandbox.agent37.app":
            assert request.headers["X-Agent37-Key"] == KEY
            assert "Authorization" not in request.headers
            return self.exec(parts[1], body)
        assert request.url.host == "api.agent37.com"
        assert request.headers["Authorization"] == "Bearer " + KEY
        if parts == ["instances"] and request.method == "POST":
            record = self.add(body)
            if self.on_create is not None:
                self.on_create(record, body)
            return httpx.Response(201, json=record)
        if parts == ["instances"]:
            ordered = sorted(self.instances.values(), key=lambda item: -item["created"])
            return httpx.Response(200, json={"data": ordered})
        record = self.instances.get(parts[1])
        if record is None:
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "No such instance"}})
        if len(parts) == 2 and request.method == "GET":
            if record.get("settle"):
                record["status"] = record["settle"].pop(0)
            return httpx.Response(200, json=record)
        if len(parts) == 2 and request.method == "DELETE":
            del self.instances[parts[1]]
            return httpx.Response(200, json={"id": parts[1], "deleted": True})
        action = parts[2]
        if action == "sleep" and record["status"] in ("running", "sleeping"):
            record["status"] = "sleeping"
        elif action == "stop" and record["status"] in ("running", "sleeping", "stopped"):
            record["status"] = "stopped"
        elif action == "start" and record["status"] in ("running", "sleeping", "stopped"):
            record["status"] = "running"
        else:
            refusal = {"code": "invalid_request", "message": f"Cannot {action} an instance that is {record['status']}"}
            return httpx.Response(400, json={"error": refusal})
        return httpx.Response(200, json={"id": parts[1], "status": record["status"]})

    def exec(self, ident, body):
        record = self.instances.get(ident)
        if record is None:
            return httpx.Response(404, json={"error": "not_found"})
        if record["status"] == "sleeping":
            # The real endpoint wakes a sleeping instance; the provider must never rely on that.
            record["status"] = "running"
        if record["status"] != "running":
            return httpx.Response(400, json={"error": {"code": "invalid_request", "message": "Not running"}})
        # Agent 37 refuses a body over 1 MB.
        assert body["user"] == "root" and len(json.dumps(body)) <= 1_000_000
        if body["name"] not in self.runs:
            self.runs[body["name"]] = self.guest(ident, body["command"])
        return httpx.Response(200, json=self.runs[body["name"]])

    def guest(self, ident, command):
        head, marker, rest = command.partition(" <<'AGNO_EOF'\n")
        data = rest[: -len("\nAGNO_EOF")].encode() if marker else b""
        argv = shlex.split(head)
        assert argv[:4] == ["python3", "-I", "-c", GUEST]
        self.executed.append(argv[4])
        base = self.root / ident
        base.mkdir(exist_ok=True)
        _guest._CONTROL, _guest._WORKSPACE, _guest._RUNTIME = base / "control", base / "workspace", base / "runtime"
        try:
            reply = json.dumps(_guest.main(argv[4:], io.BytesIO(data)))
        except Exception as error:
            return {"exit_code": 1, "stdout": "", "stderr": f"{type(error).__name__}: {error}\n", "truncated": False}
        # Agent 37 cuts each stream at 512 KB.
        assert len(reply) <= 512_000
        return {"exit_code": 0, "stdout": reply, "stderr": "", "truncated": False}


@pytest.fixture
def service(tmp_path, monkeypatch):
    for name in ("_CONTROL", "_WORKSPACE", "_RUNTIME"):
        monkeypatch.setattr(_guest, name, tmp_path)
    # Children inherit PYTHONPATH so they import this checkout.
    monkeypatch.setattr(_guest, "_PYTHON", [sys.executable])
    monkeypatch.setenv("PYTHONPATH", str(Path(_guest.__file__).resolve().parents[3]))
    # Never drop privileges or stop processes on the machine running the tests.
    monkeypatch.setattr(_guest, "_root", lambda: False)
    monkeypatch.setattr(agent37_sandbox, "_backoff", lambda attempt: 0)
    monkeypatch.setattr(agent37_sandbox, "_POLL_SECONDS", 0)
    return Service(tmp_path)


def build(service, **kwargs):
    sandbox = Agent37Sandbox(api_key=KEY, **kwargs)
    sandbox._clients = LoopClients(lambda: httpx.AsyncClient(transport=httpx.MockTransport(service.handle)))
    return sandbox


@pytest.fixture
def sandbox(service):
    return build(service)


def workspace(service, handle):
    return service.root / handle.provider_ref / "workspace"


def test_an_api_key_is_required_and_never_printed(monkeypatch):
    monkeypatch.delenv("AGENT37_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AGENT37_API_KEY"):
        Agent37Sandbox()
    monkeypatch.setenv("AGENT37_API_KEY", KEY)
    assert Agent37Sandbox()._api_key == KEY
    assert KEY not in repr(Agent37Sandbox())


def test_settings_are_validated():
    for invalid in ({"gpu": 1}, {"cpu": 0}, {"cpu": 2.5}):
        with pytest.raises(ValueError, match="resources"):
            Agent37Sandbox(api_key=KEY, resources=invalid)
    with pytest.raises(ValueError, match="template"):
        Agent37Sandbox("", api_key=KEY)
    with pytest.raises(ValueError, match="execution timeout"):
        Agent37Sandbox(api_key=KEY, execution_timeout=0)
    with pytest.raises(ValueError, match="retain_checkpoints"):
        Agent37Sandbox(api_key=KEY, retain_checkpoints=0)


def test_create_names_the_instance_after_its_generation(service):
    sandbox = build(
        service,
        template="agno-runtime",
        resources={"cpu": 4, "memory": 8},
        region="eu",
        instance_type="performance",
        network={"allow": ["api.anthropic.com"]},
    )
    handle = sandbox.create("session", agent_id="coder", generation=2, env={"ANTHROPIC_API_KEY": "secret"})
    body = service.sent("POST", "/instances")[0][3]
    assert body == {
        "template": "agno-runtime",
        "name": handle.name,
        "metadata": {
            "agno_namespace": "default",
            "agno_agent": "coder",
            "agno_session": "session",
            "agno_generation": "2",
            "agno_config": handle.config_digest,
        },
        "auto_sleep": False,
        "resources": {"cpu": 4, "memory": 8},
        "type": "performance",
        "region": "eu",
        "network": {"allow": ["api.anthropic.com"]},
        "env": {"ANTHROPIC_API_KEY": "secret"},
    }
    assert handle == SandboxHandle(
        provider_ref="inst000001",
        name=handle.name,
        agent_id="coder",
        session_id="session",
        generation=2,
        state="running",
        config_digest=handle.config_digest,
    )
    assert handle.name.startswith("agno-") and "secret" not in handle.config_digest


def test_unset_options_are_left_to_agent37_defaults(sandbox, service):
    sandbox.create("session")
    assert set(service.sent("POST", "/instances")[0][3]) == {"template", "name", "metadata", "auto_sleep"}


def test_create_is_idempotent_and_generations_are_separate(sandbox, service):
    first = sandbox.create("session", env={"A": "1"})
    assert sandbox.create("session", env={"A": "1"}) == first
    assert len(service.sent("POST", "/instances")) == 1
    assert sandbox.find("session", env={"A": "1"}) == first
    assert sandbox.find("session", generation=2) is None
    assert sandbox.create("session", generation=2).provider_ref != first.provider_ref
    with pytest.raises(SandboxError, match="different configuration"):
        sandbox.create("session", env={"A": "2"})
    with pytest.raises(SandboxError, match="different compute configuration"):
        sandbox.find("session", env={"A": "2"})


def test_a_lost_create_reply_is_resolved_by_name(sandbox, service):
    service.inject("POST", "/instances", httpx.ReadTimeout("lost"), after=True)
    handle = sandbox.create("session")
    assert list(service.instances) == [handle.provider_ref]
    assert len(service.sent("POST", "/instances")) == 1


def test_a_create_that_never_arrived_is_an_error(sandbox, service):
    service.inject("POST", "/instances", httpx.ReadTimeout("lost"))
    with pytest.raises(SandboxError, match="request failed"):
        sandbox.create("session")
    assert service.instances == {}


def test_a_refused_create_reports_the_code(sandbox, service):
    refusal = {"error": {"code": "insufficient_balance", "message": "Top up the wallet"}}
    service.inject("POST", "/instances", httpx.Response(402, json=refusal))
    with pytest.raises(SandboxError, match="insufficient_balance Top up the wallet"):
        sandbox.create("session")
    assert KEY not in str(service.requests[-1][3])


def test_a_failed_create_is_removed_so_the_generation_can_be_retried(sandbox, service):
    def fail(record, body):
        record["status"] = "failed"

    service.on_create = fail
    failure = {"error": {"code": "provisioning_failed", "message": "Boot failed"}}
    service.inject("POST", "/instances", httpx.Response(502, json=failure), after=True)
    with pytest.raises(SandboxError, match="provisioning_failed"):
        sandbox.create("session")
    assert service.instances == {}
    service.on_create = None
    assert sandbox.create("session").state == "running"


def test_overlapping_creates_settle_on_the_oldest_instance(sandbox, service):
    def race(record, body):
        # Another creator's instance of the same generation, made a moment earlier.
        service.on_create = None
        service.add(body)["created"] = 0

    service.on_create = race
    handle = sandbox.create("session")
    assert list(service.instances) == [handle.provider_ref] == ["inst000002"]
    assert sandbox.find("session") == handle


def test_find_ignores_other_namespaces_and_deletes_only_its_own_duplicates(sandbox, service):
    handle = sandbox.create("session")
    foreign = service.add({"name": handle.name, "metadata": {"agno_namespace": "other"}})
    assert sandbox.find("session") == handle
    assert foreign["id"] in service.instances
    with pytest.raises(SandboxError, match="namespace"):
        sandbox.get(foreign["id"])


def test_create_waits_for_an_instance_that_is_still_provisioning(sandbox, service):
    def provisioning(record, body):
        record.update(status="provisioning", settle=["provisioning", "running"])

    service.on_create = provisioning
    service.inject("POST", "/instances", httpx.ReadTimeout("lost"), after=True)
    assert sandbox.create("session").state == "running"


def test_get_reports_a_deleted_instance_as_gone(sandbox, service):
    handle = sandbox.create("session")
    assert sandbox.get(handle.provider_ref) == handle
    assert sandbox.get("missing") is None
    for invalid in ("", "../instances", "UPPER", "a b"):
        with pytest.raises(ValueError, match="reference"):
            sandbox.get(invalid)
    service.instances[handle.provider_ref]["status"] = "deleted"
    assert sandbox.get(handle.provider_ref) is None


def test_exec_runs_as_the_agent_in_its_workspace(sandbox, service):
    handle = sandbox.create("session")
    result = sandbox.exec(handle, ["sh", "-c", "pwd; echo $HOME; cat; echo problem >&2; exit 3"], stdin=b"input")
    assert result.exit_code == 3 and result.stderr == "problem\n"
    assert result.stdout.splitlines() == [
        str(workspace(service, handle).resolve()),
        str(service.root / handle.provider_ref / "runtime"),
        "input",
    ]
    assert service.executed == ["run"]
    assert list((service.root / handle.provider_ref / "control").iterdir()) == []


def test_exec_stages_large_input_and_reads_back_large_output(sandbox, service):
    handle = sandbox.create("session")
    payload = bytes(range(256)) * 3000
    result = sandbox.exec(handle, ["sh", "-c", "wc -c; head -c 600000 /dev/zero | tr '\\0' a"], stdin=payload)
    assert result.exit_code == 0
    count, _, filler = result.stdout.partition("\n")
    assert int(count) == len(payload) and filler == "a" * 600000
    assert service.executed.count("put") == 2 and service.executed.count("get") == 3
    assert service.executed[-1] == "remove"
    assert list((service.root / handle.provider_ref / "control").iterdir()) == []


def test_exec_validates_its_arguments_before_any_request(sandbox, service):
    handle = sandbox.create("session")
    before = len(service.requests)
    for argv in ("echo hi", [], ["echo", 1], ["a\x00b"]):
        with pytest.raises(ValueError, match="nonempty sequence"):
            sandbox.exec(handle, argv)
    with pytest.raises(ValueError, match="840 seconds"):
        sandbox.exec(handle, ["true"], timeout=841)
    with pytest.raises(ValueError, match="output limit"):
        sandbox.exec(handle, ["true"], max_output_bytes=0)
    with pytest.raises(ValueError, match="stdin"):
        sandbox.exec(handle, ["true"], stdin="text")
    assert len(service.requests) == before


def test_exec_refuses_a_stale_handle(sandbox, service):
    handle = sandbox.create("session")
    stale = SandboxHandle(**{**handle.__dict__, "generation": 9})
    with pytest.raises(SandboxError, match="identity changed"):
        sandbox.exec(stale, ["true"])
    assert service.executed == []


def test_a_dropped_reply_rejoins_the_same_run(sandbox, service):
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.ReadError("dropped"), after=True)
    result = sandbox.exec(handle, ["sh", "-c", "echo ran >> runs.txt; cat runs.txt"])
    assert result.stdout == "ran\n"
    sent = service.sent("POST", "/exec")
    assert len(sent) == 2 and sent[0][3] == sent[1][3]
    assert service.instances[handle.provider_ref]["status"] == "running"


def test_a_reply_lost_too_long_ago_is_never_resent(sandbox, service, monkeypatch):
    monkeypatch.setattr(agent37_sandbox, "_REJOIN_SECONDS", 0)
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.ReadError("dropped"), after=True)
    with pytest.raises(SandboxError, match="dropped"):
        sandbox.exec(handle, ["sh", "-c", "echo ran >> runs.txt"])
    assert len(service.sent("POST", "/exec")) == 1
    assert (workspace(service, handle) / "runs.txt").read_text() == "ran\n"
    # The command may still be running, so the instance is stopped.
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_a_late_refusal_after_a_lost_reply_is_not_resent_either(sandbox, service, monkeypatch):
    monkeypatch.setattr(agent37_sandbox, "_REJOIN_SECONDS", 1.0)
    # The resend goes out inside the window; the wait after its refusal runs past it.
    monkeypatch.setattr(agent37_sandbox, "_backoff", lambda attempt: 1.2 if attempt else 0.1)
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.ReadError("dropped"), after=True)
    service.inject("POST", "/exec", httpx.Response(503, json={"error": "try_again"}))
    with pytest.raises(SandboxError, match="try_again"):
        sandbox.exec(handle, ["sh", "-c", "echo ran >> runs.txt"])
    # By now the first send may have finished long enough ago for its name to be forgotten.
    assert len(service.sent("POST", "/exec")) == 2
    assert (workspace(service, handle) / "runs.txt").read_text() == "ran\n"
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_a_refusal_after_a_lost_reply_still_stops_the_instance(sandbox, service):
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.ReadError("dropped"), after=True)
    service.inject("POST", "/exec", httpx.Response(429, json={"error": "rate_limited"}))
    with pytest.raises(SandboxError, match="rate_limited"):
        sandbox.exec(handle, ["sh", "-c", "echo ran >> runs.txt"])
    # The refusal answers the resend, not the first send, which ran.
    assert (workspace(service, handle) / "runs.txt").read_text() == "ran\n"
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_time_lost_during_backoff_expires_the_resend(sandbox, service, monkeypatch):
    monkeypatch.setattr(agent37_sandbox, "_REJOIN_SECONDS", 0.5)

    def stalled(attempt):
        # By the time the backoff ends, Agent 37 has forgotten the first run's name.
        service.runs.clear()
        return 0.7

    monkeypatch.setattr(agent37_sandbox, "_backoff", stalled)
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.ReadError("dropped"), after=True)
    with pytest.raises(SandboxError, match="dropped"):
        sandbox.exec(handle, ["sh", "-c", "echo ran >> runs.txt"])
    assert len(service.sent("POST", "/exec")) == 1
    assert (workspace(service, handle) / "runs.txt").read_text() == "ran\n"
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_a_suspended_host_counts_toward_the_resend_window(sandbox, service, monkeypatch):
    real, skew = agent37_sandbox._now, [0.0]
    monkeypatch.setattr(agent37_sandbox, "_now", lambda: (real()[0], real()[1] + skew[0]))

    def suspended(attempt):
        # The machine slept through the backoff, so only the wall clock moved.
        skew[0] = 301.0
        service.runs.clear()
        return 0

    monkeypatch.setattr(agent37_sandbox, "_backoff", suspended)
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.ReadError("dropped"), after=True)
    with pytest.raises(SandboxError, match="dropped"):
        sandbox.exec(handle, ["sh", "-c", "echo ran >> runs.txt"])
    assert len(service.sent("POST", "/exec")) == 1
    assert (workspace(service, handle) / "runs.txt").read_text() == "ran\n"
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_a_refused_output_read_still_stops_the_instance(sandbox, service):
    handle = sandbox.create("session")
    # The run request goes through; reading back its staged output is refused.
    service.inject("POST", "/exec", httpx.Response(429, json={"error": "rate_limited"}), skip=1)
    with pytest.raises(SandboxError, match="rate_limited"):
        sandbox.exec(handle, ["sh", "-c", "echo ran > ran.txt; head -c 300000 /dev/zero | tr '\\0' a"])
    assert (workspace(service, handle) / "ran.txt").exists()
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_staged_input_is_removed_when_the_run_is_refused(sandbox, service):
    handle = sandbox.create("session")
    # Both uploads go through; the run request that would consume them is refused.
    service.inject("POST", "/exec", httpx.Response(429, json={"error": "rate_limited"}), skip=2)
    with pytest.raises(SandboxError, match="rate_limited"):
        sandbox.exec(handle, ["cat"], stdin=b"x" * 600_000)
    assert service.executed == ["put", "put", "remove"]
    assert list((service.root / handle.provider_ref / "control").iterdir()) == []
    assert service.instances[handle.provider_ref]["status"] == "running"


def test_staged_input_is_removed_when_a_runtime_request_fails(sandbox, service):
    handle = sandbox.create("session")
    payload = json.dumps({"wait": 0, "input": "x" * 600_000}).encode()
    # A runtime request never stops the instance, so what it staged must not pile up there.
    service.inject("POST", "/exec", httpx.Response(502, json={"error": "upstream_unreachable"}), times=5, skip=2)
    with pytest.raises(SandboxError, match="upstream_unreachable"):
        sandbox.rpc(handle, "start", payload)
    assert list((service.root / handle.provider_ref / "control").iterdir()) == []
    assert service.instances[handle.provider_ref]["status"] == "running"


def test_a_busy_instance_is_retried_because_nothing_started(sandbox, service):
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.Response(503, json={"error": "try_again"}), times=2)
    assert sandbox.exec(handle, ["echo", "hi"]).stdout == "hi\n"
    assert len(service.sent("POST", "/exec")) == 3


def test_a_refused_command_leaves_the_instance_running(sandbox, service):
    handle = sandbox.create("session")
    service.inject("POST", "/exec", httpx.Response(402, json={"error": "instance_suspended"}))
    with pytest.raises(SandboxError, match="instance_suspended"):
        sandbox.exec(handle, ["echo", "hi"])
    assert service.instances[handle.provider_ref]["status"] == "running"
    assert service.sent("POST", "/stop") == []


def test_an_unknown_outcome_stops_the_instance_but_not_for_a_runtime_request(sandbox, service):
    handle = sandbox.create("session")
    unreachable = httpx.Response(502, json={"error": "upstream_unreachable"})
    service.inject("POST", "/exec", unreachable, times=5)
    with pytest.raises(SandboxError, match="upstream_unreachable"):
        sandbox.rpc(handle, "poll", b'{"execution_id": "e", "cursor": 0}')
    assert service.instances[handle.provider_ref]["status"] == "running"
    service.inject("POST", "/exec", unreachable, times=5)
    with pytest.raises(SandboxError, match="upstream_unreachable"):
        sandbox.exec(handle, ["echo", "hi"])
    assert service.instances[handle.provider_ref]["status"] == "stopped"
    with pytest.raises(SandboxError, match="not running"):
        sandbox.exec(handle, ["echo", "hi"])


def test_a_command_that_times_out_stops_the_instance(sandbox, service):
    handle = sandbox.create("session")
    result = sandbox.exec(handle, ["sleep", "30"], timeout=0.2)
    assert result.timed_out
    assert service.instances[handle.provider_ref]["status"] == "stopped"


def test_truncated_output_is_never_parsed(sandbox, service):
    handle = sandbox.create("session")
    cut = {"exit_code": 0, "stdout": '{"size": 1', "stderr": "", "truncated": True}
    service.inject("POST", "/exec", httpx.Response(200, json=cut))
    with pytest.raises(SandboxError, match="truncated"):
        sandbox.exec(handle, ["echo", "hi"])


@pytest.mark.asyncio
async def test_rpc_runs_the_runtime_without_stopping_on_failure(sandbox, service, monkeypatch):
    handle = await sandbox.acreate("session")
    calls = []

    async def record(handle, argv, **kwargs):
        calls.append((argv, kwargs))

    monkeypatch.setattr(sandbox, "_aexec", record)
    await sandbox.arpc(handle, "poll", b'{"wait": 5}')
    assert calls == [
        (
            ["python3", "-I", "-m", "agno.sandbox.runtime", "poll"],
            {"timeout": 20.0, "max_output_bytes": 4 * 1024 * 1024, "stdin": b'{"wait": 5}', "stop_on_failure": False},
        )
    ]
    with pytest.raises(ValueError, match="Runtime RPC"):
        await sandbox.arpc(handle, "delete", b"{}")


def test_pause_sleeps_and_resume_wakes_the_same_generation(sandbox, service):
    handle = sandbox.create("session")
    sandbox.exec(handle, ["sh", "-c", "echo kept > file.txt"])
    sandbox.pause(handle)
    sandbox.pause(handle)
    assert len(service.sent("POST", "/sleep")) == 1
    assert sandbox.get(handle.provider_ref).state == "paused"
    # The exec API would wake the instance; only the owner may.
    with pytest.raises(SandboxError, match="paused"):
        sandbox.exec(handle, ["cat", "file.txt"])
    assert service.instances[handle.provider_ref]["status"] == "sleeping"
    with pytest.raises(SandboxError, match="paused"):
        sandbox.create("session")
    resumed = sandbox.resume(handle)
    assert resumed == handle and sandbox.resume(handle) == handle
    assert len(service.sent("POST", "/start")) == 1
    assert sandbox.exec(handle, ["cat", "file.txt"]).stdout == "kept\n"


def test_resume_waits_out_a_move_to_another_host(sandbox, service):
    handle = sandbox.create("session")
    sandbox.pause(handle)
    # A 202 acknowledges the start while the instance is still moving.
    service.inject("POST", "/start", httpx.Response(202, json={"id": handle.provider_ref, "status": "starting"}))
    service.instances[handle.provider_ref]["settle"] = ["sleeping", "sleeping", "starting", "running"]
    assert sandbox.resume(handle).state == "running"


def test_resume_refuses_a_generation_that_is_not_paused(sandbox, service):
    handle = sandbox.create("session")
    sandbox.stop(handle)
    with pytest.raises(SandboxError, match="not paused"):
        sandbox.resume(handle)
    with pytest.raises(SandboxError, match="Only a running sandbox"):
        sandbox.pause(handle)


def test_a_sleep_still_being_written_is_retried(sandbox, service):
    handle = sandbox.create("session")
    busy = {"error": {"code": "try_again", "message": "Another operation is running"}}
    service.inject("POST", "/sleep", httpx.Response(409, json=busy), times=2)
    sandbox.pause(handle)
    assert len(service.sent("POST", "/sleep")) == 3
    assert sandbox.get(handle.provider_ref).state == "paused"


def test_stop_ends_the_generation_and_destroy_removes_it(sandbox, service):
    handle = sandbox.create("session")
    sandbox.stop(handle)
    sandbox.stop(handle)
    assert len(service.sent("POST", "/stop")) == 1
    assert sandbox.get(handle.provider_ref).state == "stopped"
    with pytest.raises(SandboxError, match="new generation"):
        sandbox.create("session")
    sandbox.destroy(handle)
    sandbox.destroy(handle)
    assert sandbox.get(handle.provider_ref) is None and service.instances == {}
    assert len(service.sent("DELETE", handle.provider_ref)) == 1


def test_a_paused_generation_can_be_stopped_and_destroyed(sandbox, service):
    handle = sandbox.create("session")
    sandbox.pause(handle)
    sandbox.stop(handle)
    assert sandbox.get(handle.provider_ref).state == "stopped"
    sandbox.destroy(handle)
    assert service.instances == {}


@pytest.fixture
def transfer(sandbox, tmp_path):
    return sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "store"))


def test_the_transfer_satisfies_the_transfer_protocol(transfer):
    assert isinstance(transfer, Agent37CheckpointTransfer) and isinstance(transfer, CheckpointTransfer)


def test_checkpoint_round_trip_into_a_replacement_instance(sandbox, service, transfer):
    first = sandbox.create("session")
    script = (
        "mkdir -p $HOME/native/codex/.tmp/plugins src && echo conversation > $HOME/native/session.json && "
        "echo cache > $HOME/native/codex/.tmp/plugins/market && echo secret > $HOME/native/codex/auth.json && "
        "head -c 700000 /dev/urandom > src/blob.bin && echo code > src/main.py && ln -s main.py src/link"
    )
    assert sandbox.exec(first, ["sh", "-c", script]).exit_code == 0
    blob = (workspace(service, first) / "src/blob.bin").read_bytes()
    service.executed.clear()
    reference = transfer.capture(first, state={"native_session_id": "abc"})
    # The archive is larger than one reply carries, so it came back in chunks and was then removed.
    assert service.executed[0] == "capture" and service.executed.count("get") >= 3
    assert service.executed[-1] == "remove"
    sandbox.destroy(first)

    second = sandbox.create("session", generation=2)
    service.executed.clear()
    assert transfer.restore(second, reference) == {"native_session_id": "abc"}
    assert service.executed.count("put") == 2 and service.executed[-1] == "restore"
    restored = workspace(service, second)
    assert (restored / "src/blob.bin").read_bytes() == blob
    assert (restored / "src/main.py").read_text() == "code\n" and (restored / "src/link").is_symlink()
    native = service.root / second.provider_ref / "runtime/native"
    assert (native / "session.json").read_text() == "conversation\n"
    # Credentials and the plugin cache never leave the instance.
    assert not (native / "codex/auth.json").exists() and not (native / "codex/.tmp/plugins").exists()
    assert list((service.root / second.provider_ref / "control").iterdir()) == []
    assert service.instances[second.provider_ref]["status"] == "running"


def test_capture_defaults_to_the_exclusions_for_remote_transfers(transfer):
    assert Agent37CheckpointTransfer.acapture.__kwdefaults__["exclude"] == REMOTE_NATIVE_EXCLUSIONS
    assert Agent37CheckpointTransfer.capture.__kwdefaults__["exclude"] == REMOTE_NATIVE_EXCLUSIONS


def test_capture_refuses_to_exclude_a_whole_root_before_any_request(sandbox, service, transfer):
    handle = sandbox.create("session")
    before = len(service.requests)
    with pytest.raises(ValueError, match="entire durable root"):
        transfer.capture(handle, state={}, exclude=["workspace"])
    assert len(service.requests) == before


def test_capture_needs_a_running_instance(sandbox, service, transfer):
    handle = sandbox.create("session")
    sandbox.pause(handle)
    with pytest.raises(SandboxError, match="running, exclusively owned"):
        transfer.capture(handle, state={})
    assert service.instances[handle.provider_ref]["status"] == "sleeping"


def test_a_failed_capture_leaves_the_instance_running(sandbox, service, transfer):
    handle = sandbox.create("session")
    sandbox.exec(handle, ["sh", "-c", "mkfifo pipe"])
    with pytest.raises(SandboxError, match="capture failed"):
        transfer.capture(handle, state={})
    assert service.instances[handle.provider_ref]["status"] == "running"
    assert list((service.root / handle.provider_ref / "control").iterdir()) == []


def test_a_failed_restore_stops_the_instance(sandbox, service, transfer):
    first = sandbox.create("session")
    sandbox.exec(first, ["sh", "-c", "echo code > main.py"])
    reference = transfer.capture(first, state={})
    used = sandbox.create("session", generation=2)
    sandbox.exec(used, ["sh", "-c", "echo stray > stray.txt"])
    with pytest.raises(SandboxError, match="empty, unused generation"):
        transfer.restore(used, reference)
    assert service.instances[used.provider_ref]["status"] == "stopped"
    assert not (workspace(service, used) / "main.py").exists()


def test_a_checkpoint_that_cannot_be_read_leaves_the_instance_alone(sandbox, service, transfer):
    handle = sandbox.create("session")
    before = len(service.requests)
    with pytest.raises(CheckpointObjectNotFound):
        transfer.restore(handle, CheckpointRef("0" * 64, 10))
    assert len(service.requests) == before
    assert service.instances[handle.provider_ref]["status"] == "running"


def test_an_archive_altered_in_transit_is_refused(sandbox, service, transfer, monkeypatch):
    handle = sandbox.create("session")
    sandbox.exec(handle, ["sh", "-c", "head -c 400000 /dev/urandom > blob.bin"])
    real = _guest._get

    def corrupt(name, offset, length):
        reply = real(name, offset, length)
        return {"data": reply["data"][:400] + "AAAAAAAA" + reply["data"][408:]} if offset == "0" else reply

    monkeypatch.setattr(_guest, "_get", corrupt)
    with pytest.raises(SandboxError, match="does not match its digest"):
        transfer.capture(handle, state={})


# The in-instance script


@pytest.fixture
def staging(tmp_path, monkeypatch):
    monkeypatch.setattr(_guest, "_CONTROL", tmp_path / "control")
    monkeypatch.setattr(_guest, "_WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(_guest, "_RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(_guest, "_root", lambda: False)
    _guest._prepare()
    return tmp_path / "control"


NAME = "a" * 32


def test_staged_names_cannot_leave_the_staging_directory(staging):
    for name in ("../escape", "short", "A" * 32, NAME + "/x"):
        with pytest.raises(ValueError, match="staged object name"):
            _guest.main(["remove", name], io.BytesIO())


def test_chunks_land_by_offset_in_any_order(staging):
    for offset, data in ((3, b"def"), (0, b"abc"), (3, b"def")):
        _guest.main(["put", NAME, str(offset)], io.BytesIO(base64.b64encode(data) + b"\n"))
    assert (staging / (NAME + ".in")).read_bytes() == b"abcdef"
    with pytest.raises(ValueError, match="offset"):
        _guest.main(["put", NAME, "-1"], io.BytesIO(b""))


def test_staged_input_that_is_not_what_was_sent_never_runs(staging, tmp_path):
    request = json.dumps({"argv": ["touch", "ran"], "timeout": 5, "max_output_bytes": 100}).encode()
    _guest.main(["put", NAME, "0"], io.BytesIO(base64.b64encode(request)))
    runner = Path(agent37_sandbox.__file__).parent.parent.joinpath("_exec.py").read_text()
    with pytest.raises(ValueError, match="not what was sent"):
        _guest.main(["run", NAME, runner, str(len(request)), "0" * 64], io.BytesIO())
    assert not (tmp_path / "workspace/ran").exists()
    digest = hashlib.sha256(request).hexdigest()
    reply = _guest.main(["run", NAME, runner, str(len(request)), digest], io.BytesIO())
    assert json.loads(base64.b64decode(reply["data"]))["exit_code"] == 0
    assert (tmp_path / "workspace/ran").exists() and list(staging.iterdir()) == []


def test_files_an_abandoned_operation_left_staged_are_swept(staging):
    abandoned, current = staging / ("b" * 32 + ".in"), staging / ("c" * 32 + ".in")
    abandoned.write_bytes(b"left behind")
    current.write_bytes(b"in use")
    hours_ago = time.time() - 2 * 3600
    os.utime(abandoned, (hours_ago, hours_ago))
    _guest.main(["remove", NAME], io.BytesIO())
    assert sorted(entry.name for entry in staging.iterdir()) == [current.name]


def test_unknown_operations_and_wrong_argument_counts_are_refused(staging):
    for arguments in (["shell"], ["run", NAME], ["get", NAME, "0"], ["restore", NAME, "{}"]):
        with pytest.raises(ValueError, match="Unknown sandbox operation"):
            _guest.main(arguments, io.BytesIO())
    with pytest.raises(ValueError, match="at most 256 KiB"):
        _guest.main(["get", NAME, "0", str(1024 * 1024)], io.BytesIO())


def test_freeze_stops_new_processes_and_leaves_those_the_agent_stopped(monkeypatch):
    signals = []
    monkeypatch.setattr(_guest, "_agent_pids", lambda: [10, 11])
    monkeypatch.setattr(_guest, "_process_state", lambda pid: "T" if pid == 10 else "S")
    monkeypatch.setattr(_guest.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    stopped = _guest._freeze()
    assert stopped == [11] and signals == [(11, signal.SIGSTOP)]
    _guest._thaw(stopped)
    assert signals[-1] == (11, signal.SIGCONT)


@pytest.mark.skipif(os.geteuid() == 0, reason="As root the directory this creates does belong to root")
def test_the_staging_directory_must_belong_to_root_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(_guest, "_CONTROL", tmp_path / "control")
    monkeypatch.setattr(_guest, "_WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(_guest, "_RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(_guest, "_root", lambda: True)
    with pytest.raises(PermissionError, match="root alone"):
        _guest._prepare()
