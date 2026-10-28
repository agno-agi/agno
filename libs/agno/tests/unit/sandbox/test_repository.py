"""Repository configuration and real local Git preparation without model calls."""

import asyncio
import base64
import json
import subprocess
import sys
import tarfile
import threading
import time

import pytest

from agno.sandbox import Repository, repository
from agno.sandbox.checkpoint import CheckpointArchive
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS

SPEC = {"url": "https://github.com/example/application", "branch": "main"}


@pytest.fixture
def local_repository(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    real_run = subprocess.run

    def git(*args, cwd=source):
        return real_run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (source / "app.py").write_text("version = 1\n")
    git("add", ".")
    git("commit", "-m", "initial")
    sha = git("rev-parse", "HEAD")
    calls = []

    def local_run(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        if "fetch" in args or "ls-remote" in args:
            args = [str(source) if value == "origin" else value for value in args]
        return real_run(args, **kwargs)

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(repository.subprocess, "run", local_run)
    return source, sha, calls, git


def test_prepare_resume_and_replacement_keep_commits_and_edits(tmp_path, local_repository):
    source, sha, calls, git = local_repository
    workspace, native = tmp_path / "workspace", tmp_path / "runtime/native"
    target = repository._prepare(SPEC, workspace, native, resume=False)
    pin = {**SPEC, "commit": sha}
    assert json.loads((native / "repository.json").read_text()) == pin
    assert git("rev-parse", "HEAD", cwd=target) == sha
    assert git("rev-parse", "--is-shallow-repository", cwd=target) == "true"
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=target) == "HEAD"
    # The remote can advance after this session has been pinned.
    (source / "app.py").write_text("version = 2\n")
    git("commit", "-am", "remote advance")
    git("config", "user.email", "test@example.com", cwd=target)
    git("config", "user.name", "Test", cwd=target)
    (target / "app.py").write_text("version = 3\n")
    git("commit", "-am", "engineer", cwd=target)
    engineer_head = git("rev-parse", "HEAD", cwd=target)
    (target / "app.py").write_text("version = 4\n")
    (target / "untracked").write_text("keep me")
    count = len(calls)
    repository._prepare(SPEC, workspace, native, resume=True)
    assert len(calls) == count
    archive = CheckpointArchive()
    checkpoint = tmp_path / "checkpoint.tar"
    archive.capture({"workspace": workspace, "native": native}, checkpoint, state={}, exclude=DEFAULT_NATIVE_EXCLUSIONS)
    restored = tmp_path / "replacement"
    archive.restore(checkpoint, restored)
    checkout = repository._prepare(SPEC, restored / "workspace", restored / "native", resume=True)
    assert len(calls) == count
    assert git("rev-parse", "HEAD", cwd=checkout) == engineer_head
    assert (checkout / "app.py").read_text() == "version = 4\n"
    assert (checkout / "untracked").read_text() == "keep me"
    assert repository._read_pin(restored / "native", SPEC) == pin
    for changed in ({**SPEC, "branch": "other"}, {**SPEC, "url": "https://github.com/other/repo"}):
        with pytest.raises(ValueError, match="pinned source"):
            repository._prepare(changed, workspace, native, resume=True)
    (native / "repository.json").unlink()
    with pytest.raises(repository.RepositoryPreparationError, match="source identity"):
        repository._prepare(SPEC, workspace, native, resume=True)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/repo",
        "https://token@github.com/a/b",
        "https://evil.test/a/b",
        "https://github.com/../b",
        "https://github.com/a/b?token=secret",
        "https://github.com/a/b#main",
        "https://github.com:443/a/b",
    ],
)
def test_invalid_url(url):
    with pytest.raises(ValueError, match="repository.url"):
        Repository(url)


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "-main",
        "HEAD",
        "a..b",
        "a.lock",
        "a.lock/b",
        ".a",
        "a/.b",
        "a/",
        "/a",
        "a//b",
        "a.",
        "a@{b",
        "a b",
        "a~b",
        "a^b",
        "a:b",
        "a?b",
        "a*b",
        "a[b",
        "a\\b",
        "a\n",
        "a\x7fb",
        "main",
        "feature/nested",
        "@",
        "a@b",
        "release-v1",
        "refs/heads/main",
        "café",
    ],
)
def test_branch_rules_match_git(branch):
    valid = subprocess.run(["git", "check-ref-format", "--branch", branch], capture_output=True).returncode == 0
    if valid:
        assert Repository(SPEC["url"], branch).branch == branch
    else:
        with pytest.raises(ValueError, match="repository.branch"):
            Repository(SPEC["url"], branch)


def test_config_validation_has_no_subprocess(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("configuration invoked Git"))
    assert Repository(SPEC["url"]).branch == "main"
    for value in ({**SPEC, "token": "secret"}, {"url": SPEC["url"], "commit": "a" * 40}):
        with pytest.raises(ValueError):
            repository.validate_repository(value)


@pytest.mark.parametrize("sdk", ["claude", "codex"])
def test_agent_configuration_and_run_rejection(sdk, monkeypatch):
    from agno.agents.claude import ClaudeAgent
    from agno.agents.codex import CodexAgent
    from agno.sandbox._harness import _execution, env, submission
    from agno.sandbox.docker import DockerSandbox

    cls = ClaudeAgent if sdk == "claude" else CodexAgent
    configured = Repository(**SPEC)
    with pytest.raises(ValueError, match="repository requires sandbox"):
        cls(repository=configured)
    with pytest.raises(TypeError, match="Repository"):
        cls(repository=SPEC)
    agent = cls(sandbox=DockerSandbox(image="fixture"), repository=configured)
    assert _execution(agent, "inspect", {})["config"]["repository"] == SPEC
    assert submission(agent, "inspect", {}) == {}
    monkeypatch.setenv("GITHUB_READ_TOKEN", "host-only-secret")
    assert "GITHUB_READ_TOKEN" not in env(agent)
    for method in (agent.run, agent.arun):
        for stream in (False, True):
            with pytest.raises(ValueError, match="agent.repository"):
                method("inspect", repository=None, stream=stream)
    with pytest.raises(ValueError, match="Unsupported sandbox run options: repository"):
        submission(agent, "inspect", {"repository": SPEC})
    with pytest.raises(ValueError, match="GITHUB_READ_TOKEN"):
        cls(sandbox=DockerSandbox(image="fixture", env={"GITHUB_TOKEN": "publishing-secret"}), repository=configured)
    unrestricted = cls(sandbox=DockerSandbox(image="fixture", env={"GITHUB_TOKEN": "publishing-secret"}))
    assert env(unrestricted)["GITHUB_TOKEN"] == "publishing-secret"


def test_token_only_in_child_environment(tmp_path, monkeypatch, local_repository):
    _, _, calls, _ = local_repository
    token = "read-secret-never-store"
    encoded = base64.b64encode(("x-access-token:" + token).encode()).decode()
    monkeypatch.setenv("GITHUB_READ_TOKEN", token)
    monkeypatch.setenv("GIT_TRACE", str(tmp_path / "workspace/trace"))
    workspace, native = tmp_path / "workspace", tmp_path / "runtime/native"
    repository._prepare(SPEC, workspace, native, resume=False)
    for args, kwargs in calls:
        assert token not in str(args) and encoded not in str(args)
        env = kwargs["env"]
        assert "GITHUB_READ_TOKEN" not in env and "GIT_TRACE" not in env
        assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert kwargs["timeout"] == 120
        settings = {
            env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))
        }
        assert settings["http.followRedirects"] == "false"
        assert settings["http.https://github.com/.extraheader"] == "Authorization: Basic " + encoded
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert token.encode() not in path.read_bytes() and encoded.encode() not in path.read_bytes()
    archive = tmp_path / "checkpoint.tar"
    CheckpointArchive(compress=False).capture(
        {"workspace": workspace, "native": native}, archive, state={}, exclude=DEFAULT_NATIVE_EXCLUSIONS
    )
    assert token.encode() not in archive.read_bytes() and encoded.encode() not in archive.read_bytes()
    with tarfile.open(archive) as contents:
        assert "native/repository.json" in contents.getnames()


@pytest.mark.parametrize("failure", ["exit", "timeout", "oserror", "marker"])
def test_failed_preparation_redacts_and_cleans(tmp_path, monkeypatch, local_repository, failure):
    _, _, _, _ = local_repository
    secret = "credential-must-not-escape"
    monkeypatch.setenv("GITHUB_READ_TOKEN", secret)
    local_run = repository.subprocess.run

    def failed(args, **kwargs):
        if "fetch" in args:
            if failure == "exit":
                return subprocess.CompletedProcess(args, 1, secret, secret)
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 120, output=secret, stderr=secret)
            if failure == "oserror":
                raise OSError(secret)
        return local_run(args, **kwargs)

    monkeypatch.setattr(repository.subprocess, "run", failed)
    workspace, native = tmp_path / "workspace", tmp_path / "runtime/native"
    if failure == "marker":
        native.parent.mkdir()
        native.write_text("not a directory")
    with pytest.raises(repository.RepositoryPreparationError) as caught:
        repository._prepare(SPEC, workspace, native, resume=False)
    assert secret not in str(caught.value)
    assert not (workspace / "repository").exists()
    assert not (workspace / ".repository-prepare").exists()


@pytest.mark.asyncio
async def test_cancellation_drains_preparation(tmp_path, monkeypatch, local_repository):
    started, release = threading.Event(), threading.Event()
    original = repository._prepare

    def delayed(*args, **kwargs):
        started.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "_prepare", delayed)
    task = asyncio.create_task(repository._aprepare(SPEC, tmp_path / "workspace", tmp_path / "native", resume=False))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "workspace/.repository-prepare").exists()


@pytest.mark.asyncio
async def test_runtime_guards_before_model(tmp_path, monkeypatch):
    from agno.sandbox import runtime

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    native = tmp_path / "native"
    native.mkdir()
    (native / "repository.json").write_text(json.dumps({**SPEC, "commit": "a" * 40}))
    directory = tmp_path / "jobs/run"
    directory.mkdir(parents=True)
    monkeypatch.setattr(runtime, "_execute_harness", lambda *a: pytest.fail("model started"))
    with pytest.raises(ValueError, match="agent.repository"):
        await runtime._execute(directory, {"sdk": "fixture", "config": {}})
    with pytest.raises(ValueError, match="pinned source"):
        await runtime._execute(directory, {"sdk": "fixture", "config": {"repository": {**SPEC, "branch": "other"}}})


def test_uploads_stay_out_of_the_checkout_index(tmp_path, local_repository):
    _, _, _, git = local_repository
    target = repository._prepare(SPEC, tmp_path / "workspace", tmp_path / "runtime/native", resume=False)
    upload = target / ".agno/uploads/run-1/brief.pdf"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"%PDF")
    (target / "notes.txt").write_text("tracked")
    git("add", ".", cwd=target)
    assert git("status", "--porcelain", "--untracked-files=all", cwd=target).splitlines() == ["A  notes.txt"]
    # A checkout restored from a checkpoint taken before the exclusion existed gets it on resume, once.
    (target / ".git/info/exclude").unlink()
    for _ in range(2):
        assert repository._prepare(SPEC, tmp_path / "workspace", tmp_path / "runtime/native", resume=True) == target
    assert (target / ".git/info/exclude").read_text() == "/.agno/\n"
    assert git("status", "--porcelain", "--untracked-files=all", cwd=target).splitlines() == ["A  notes.txt"]


@pytest.mark.parametrize("sdk", ["claude", "codex"])
def test_runtime_sets_repository_cwd(tmp_path, sdk):
    from agno.sandbox import runtime

    agent = runtime._agent({"agent_id": "agent", "sdk": sdk, "config": {"repository": SPEC}}, tmp_path)
    try:
        assert str(agent.cwd) == "/workspace/repository"
        assert agent.repository is None
    finally:
        agent.db.db_engine.dispose()


def test_worker_preparation_failure_is_retryable_before_model(tmp_path, monkeypatch):
    from agno.sandbox import runtime

    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    directory = tmp_path / "jobs/first"
    directory.mkdir(parents=True)
    request = {
        "version": 1,
        "execution_id": "first",
        "sdk": "fixture",
        "input": "inspect",
        "agent_id": "a",
        "session_id": "s",
        "run_id": "r",
        "config": {"repository": SPEC},
    }
    (directory / "request.json").write_text(json.dumps(request))

    async def fail(*args, **kwargs):
        raise repository.RepositoryPreparationError("Repository preparation failed")

    monkeypatch.setattr(repository, "_aprepare", fail)
    monkeypatch.setattr(runtime, "_execute_harness", lambda *args: pytest.fail("model started"))
    runtime._worker(directory)
    result = json.loads((directory / "result.json").read_text())
    assert result["type"] == "execution_error"
    assert result["reason"] == "repository_preparation_failed"


def test_worker_gives_the_token_to_preparation_and_not_to_the_harness(tmp_path, monkeypatch):
    import os

    from agno.sandbox import runtime

    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    monkeypatch.setenv("GITHUB_READ_TOKEN", "read-secret")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    directory = tmp_path / "jobs/first"
    directory.mkdir(parents=True)
    request = {
        "version": 1,
        "execution_id": "first",
        "sdk": "fixture",
        "input": "inspect",
        "agent_id": "a",
        "session_id": "s",
        "run_id": "r",
        "config": {"repository": SPEC},
    }
    (directory / "request.json").write_text(json.dumps(request))
    seen = {}

    async def prepare(*args, token=None, **kwargs):
        seen["token"], seen["preparation_env"] = token, os.environ.get("GITHUB_READ_TOKEN")

    async def harness(*args):
        seen["harness_env"] = os.environ.get("GITHUB_READ_TOKEN")
        # The SDKs start their CLIs with the inherited environment, as any subprocess does.
        child = subprocess.run(
            [sys.executable, "-c", "import os; print(os.environ.get('GITHUB_READ_TOKEN'))"],
            capture_output=True,
            text=True,
            check=True,
        )
        seen["child_env"] = child.stdout.strip()
        return {"type": "execution_finished"}

    monkeypatch.setattr(repository, "_aprepare", prepare)
    monkeypatch.setattr(repository, "_read_pin", lambda *args: {})
    monkeypatch.setattr(runtime, "_execute_harness", harness)
    runtime._worker(directory)
    assert json.loads((directory / "result.json").read_text())["type"] == "execution_finished"
    assert seen == {"token": "read-secret", "preparation_env": None, "harness_env": None, "child_env": "None"}


def test_prepare_uses_a_token_passed_by_the_worker(tmp_path, local_repository, monkeypatch):
    _, _, calls, _ = local_repository
    monkeypatch.delenv("GITHUB_READ_TOKEN", raising=False)
    encoded = base64.b64encode(b"x-access-token:read-secret").decode()
    repository._prepare(SPEC, tmp_path / "workspace", tmp_path / "runtime/native", resume=False, token="read-secret")
    env = calls[0][1]["env"]
    settings = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert settings["http.https://github.com/.extraheader"] == "Authorization: Basic " + encoded


def test_runtime_fingerprint_includes_repository(tmp_path, monkeypatch):
    from agno.sandbox import SandboxError, runtime

    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: None)
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "test-start")
    request = {
        "version": 1,
        "execution_id": "first",
        "sdk": "fixture",
        "input": "inspect",
        "agent_id": "a",
        "session_id": "s",
        "run_id": "r",
        "config": {"repository": SPEC},
    }
    runtime._start(tmp_path, request)
    request["config"]["repository"] = {**SPEC, "branch": "other"}
    with pytest.raises(SandboxError, match="different input"):
        runtime._start(tmp_path, request)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["commit", "branch"])
async def test_first_turn_override_and_marker_wins(tmp_path, monkeypatch, local_repository, kind):
    from agno.sandbox import runtime

    source, sha, calls, git = local_repository
    git("branch", "chosen")
    (source / "app.py").write_text("default branch advanced")
    git("commit", "-am", "default advance")
    default_head = git("rev-parse", "HEAD")
    assert sha != default_head
    root = tmp_path / "computer"
    directory = root / "jobs/first"
    directory.mkdir(parents=True)
    workspace, native = root / "workspace", root / "native"
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(workspace))
    override = {"commit": sha.upper()} if kind == "commit" else {"branch": "chosen"}
    request = {
        "sdk": "fixture",
        "input": "inspect",
        "agent_id": "agent",
        "session_id": "session",
        "run_id": "first",
        "config": {"repository": SPEC},
        "metadata": {"repository": override},
    }
    first = await runtime._execute(directory, request)
    expected = {**SPEC, "commit": sha, "branch": "chosen" if kind == "branch" else "main"}
    assert first["repository"] == repository._read_pin(native, SPEC) == expected
    assert git("rev-parse", "HEAD", cwd=workspace / "repository") == sha
    if kind == "commit":
        assert not any("ls-remote" in args for args, _ in calls)
    else:
        assert json.loads((native / "repository.json").read_text())["configured_branch"] == "main"
    count = len(calls)
    (workspace / "repository/app.py").write_text("engineer edit")
    request["native_session_id"] = first["session"]["session_data"]["fixture_session_id"]
    for later in (override, {"commit": default_head}, {"branch": "nonexistent"}):
        request["metadata"] = {"repository": later}
        result = await runtime._execute(directory, request)
        assert result["repository"] == expected
        assert (workspace / "repository/app.py").read_text() == "engineer edit"
        assert len(calls) == count
    checkpoint = tmp_path / "override-checkpoint.tar"
    archive = CheckpointArchive()
    archive.capture({"workspace": workspace, "native": native}, checkpoint, state={})
    replacement = tmp_path / "replacement"
    archive.restore(checkpoint, replacement)
    repository._prepare(
        SPEC, replacement / "workspace", replacement / "native", resume=True, override={"branch": "other"}
    )
    assert repository._read_pin(replacement / "native", SPEC) == expected
    assert len(calls) == count
    with pytest.raises(ValueError, match="pinned source"):
        repository._prepare(
            {**SPEC, "branch": "changed-agent"}, replacement / "workspace", replacement / "native", resume=True
        )


@pytest.mark.parametrize(
    "override",
    [
        {"url": SPEC["url"], "commit": "a" * 40},
        {"url": "https://github.com/other/repo", "branch": "main"},
        {"commit": "short"},
        {"commit": 123},
        {"branch": "../invalid"},
        {"branch": "-invalid"},
        {"branch": "main", "commit": "a" * 40},
        {},
        None,
    ],
)
def test_invalid_metadata_refused_without_network(tmp_path, monkeypatch, override):
    from agno.agents.codex import CodexAgent
    from agno.sandbox._harness import submission
    from agno.sandbox.docker import DockerSandbox

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("network/Git called"))
    agent = CodexAgent(sandbox=DockerSandbox(image="fixture"), repository=Repository(**SPEC))
    with pytest.raises(ValueError):
        submission(agent, "inspect", {"metadata": {"repository": override}})


@pytest.mark.asyncio
async def test_url_override_rejected_even_when_marker_exists(tmp_path, monkeypatch, local_repository):
    from agno.sandbox import runtime

    root = tmp_path / "computer"
    directory = root / "jobs/first"
    directory.mkdir(parents=True)
    workspace, native = root / "workspace", root / "native"
    repository._prepare(SPEC, workspace, native, resume=False)
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(workspace))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("network/Git called"))
    monkeypatch.setattr(runtime, "_execute_harness", lambda *a: pytest.fail("model called"))
    for url in (SPEC["url"], "https://github.com/other/repo"):
        with pytest.raises(ValueError, match="url cannot be overridden"):
            await runtime._execute(
                directory,
                {"config": {"repository": SPEC}, "metadata": {"repository": {"url": url, "commit": "a" * 40}}},
            )


@pytest.mark.parametrize("method", ["run", "arun", "stream"])
def test_coordinator_wrappers_preserve_metadata(method):
    from types import SimpleNamespace

    from agno.run.agent import RunOutput
    from agno.sandbox.coordinator import SandboxCoordinator

    coordinator = SandboxCoordinator.__new__(SandboxCoordinator)
    coordinator.store = SimpleNamespace(db=None, _sync=lambda fn, *a, **kw: asyncio.run(fn(*a, **kw)))
    captured = []

    async def stream(session_id, **kwargs):
        captured.append(kwargs)
        yield RunOutput(run_id="r")

    coordinator.astream = stream
    metadata = {"repository": {"commit": "a" * 40}}
    value = getattr(coordinator, method)(
        "session", agent_id="a", run_id="r", input="inspect", sdk="fixture", metadata=metadata
    )
    if method == "arun":
        asyncio.run(value)
    elif method == "stream":
        list(value)
    assert captured[0]["metadata"] == metadata


@pytest.mark.parametrize("sync", [False, True])
def test_runtime_client_preserves_metadata(sync):
    from agno.sandbox import SandboxHandle
    from agno.sandbox.client import SandboxRuntimeClient

    client = SandboxRuntimeClient(None)
    captured = []

    async def rpc(handle, operation, request):
        captured.append(request)
        return {"accepted": True}

    client._rpc = rpc
    handle = SandboxHandle("ref", "name", "a", "s", 1, "running", "digest")
    metadata = {"repository": {"branch": "release"}}
    kwargs = dict(execution_id="e", run_id="r", sdk="fixture", input="inspect", metadata=metadata)
    if sync:
        client.start(handle, **kwargs)
    else:
        asyncio.run(client.astart(handle, **kwargs))
    assert captured[0]["metadata"] == metadata


@pytest.mark.parametrize("phase", ["preparation", "harness"])
def test_worker_timeout_retryability_matches_execution_boundary(tmp_path, monkeypatch, local_repository, phase):
    from agno.sandbox import runtime

    _, sha, _, _ = local_repository
    directory = tmp_path / "runtime/jobs/timeout"
    directory.mkdir(parents=True)
    workspace, native = tmp_path / "workspace", tmp_path / "runtime/native"
    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(workspace))
    local_run = subprocess.run
    fetched = []
    model_calls = []

    def delayed_fetch(args, **kwargs):
        if "fetch" in args:
            fetched.append(True)
            time.sleep(1.1)
        return local_run(args, **kwargs)

    async def harness(*args):
        model_calls.append(True)
        await asyncio.sleep(10)

    if phase == "preparation":
        monkeypatch.setattr(subprocess, "run", delayed_fetch)
    else:
        repository._prepare(SPEC, workspace, native, resume=False)
    monkeypatch.setattr(runtime, "_execute_harness", harness)
    request = dict(
        version=1,
        execution_id="timeout",
        sdk="fixture",
        input="inspect",
        agent_id="a",
        session_id="s",
        run_id="r",
        config={"repository": SPEC},
        execution_timeout=1,
    )
    (directory / "request.json").write_text(json.dumps(request))
    runtime._worker(directory)
    result = json.loads((directory / "result.json").read_text())
    assert result["type"] == "execution_error"
    assert repository._read_pin(native, SPEC)["commit"] == sha
    assert not (workspace / ".repository-prepare").exists()
    if phase == "preparation":
        assert fetched and not model_calls
        assert result.get("reason") == "repository_preparation_failed"
    else:
        assert model_calls
        assert result["error"] == "TimeoutError"
        assert "reason" not in result


@pytest.mark.parametrize("lost", ["native", "marker", "checkout"])
def test_worker_missing_repository_state_is_retryable_before_model(tmp_path, monkeypatch, local_repository, lost):
    import shutil

    from agno.sandbox import runtime

    directory = tmp_path / "runtime/jobs/resume"
    directory.mkdir(parents=True)
    workspace, native = tmp_path / "workspace", tmp_path / "runtime/native"
    repository._prepare(SPEC, workspace, native, resume=False)
    if lost == "native":
        shutil.rmtree(native)
    elif lost == "marker":
        (native / "repository.json").unlink()
    else:
        shutil.rmtree(workspace / "repository")
    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(workspace))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("restore attempted network access"))
    monkeypatch.setattr(runtime, "_execute_harness", lambda *a: pytest.fail("model started"))
    request = dict(
        version=1,
        execution_id="resume",
        sdk="fixture",
        input="inspect",
        agent_id="a",
        session_id="s",
        run_id="r",
        config={"repository": SPEC},
        native_session_id="previous",
    )
    (directory / "request.json").write_text(json.dumps(request))
    runtime._worker(directory)
    result = json.loads((directory / "result.json").read_text())
    assert result["type"] == "execution_error"
    assert result.get("reason") == "repository_preparation_failed"


@pytest.mark.asyncio
async def test_non_repository_runtime_keeps_github_token_support(tmp_path, monkeypatch):
    from agno.sandbox import runtime

    directory = tmp_path / "jobs/first"
    directory.mkdir(parents=True)
    monkeypatch.setenv("GITHUB_TOKEN", "publishing-token")
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(tmp_path / "workspace"))
    request = dict(sdk="fixture", input="inspect", agent_id="a", session_id="s", run_id="r", config={})
    result = await runtime._execute(directory, request)
    assert result["type"] == "execution_finished"


@pytest.mark.parametrize("failure", ["publishing_token", "marker_deleted_by_harness"])
def test_runtime_repository_failure_boundaries(tmp_path, monkeypatch, local_repository, failure):
    from agno.sandbox import runtime

    directory = tmp_path / "runtime/jobs/boundary"
    directory.mkdir(parents=True)
    workspace, native = tmp_path / "workspace", tmp_path / "runtime/native"
    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(workspace))
    model_calls = []

    async def harness(directory, request):
        model_calls.append(True)
        result = await runtime._fixture(directory, request)
        (native / "repository.json").unlink()
        return result

    monkeypatch.setattr(runtime, "_execute_harness", harness)
    if failure == "publishing_token":
        monkeypatch.setenv("GITHUB_TOKEN", "publishing-secret")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("Git started"))
    request = dict(
        version=1,
        execution_id="boundary",
        sdk="fixture",
        input="inspect",
        agent_id="a",
        session_id="s",
        run_id="r",
        config={"repository": SPEC},
    )
    (directory / "request.json").write_text(json.dumps(request))
    runtime._worker(directory)
    result = json.loads((directory / "result.json").read_text())
    assert result["type"] == "execution_error"
    assert "reason" not in result
    if failure == "publishing_token":
        assert not model_calls
        assert "GITHUB_READ_TOKEN" in result["error"]
        assert "publishing-secret" not in result["error"]
    else:
        # Once tools have run, losing the marker must not authorize replaying them.
        assert model_calls
        assert (workspace / "fixture-effects.txt").read_text() == "r\n"
        assert "pinned source" in result["error"]
