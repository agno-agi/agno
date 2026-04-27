"""Unit tests for GitHubContextProvider.

The strategy: spin up a bare git repo in tmp_path as the "remote",
seed one commit, and point the provider at it via a custom ``root``.
No network, no GitHub. ``gh`` is stubbed via a fake script on PATH.
"""

from __future__ import annotations

import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from agno.context.github import GitHubContextProvider
from agno.context.github.provider import _parse_repo, _sanitize_task
from agno.context.github.tools import GitReadTools, GitWriteTools
from agno.context.mode import ContextMode

# ---------------------------------------------------------------------------
# Helpers — fake remote + provider factory
# ---------------------------------------------------------------------------


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


def _make_fake_remote(tmp_path: Path) -> Path:
    """Create a bare repo with one commit on ``main``, return its path."""
    bare = tmp_path / "fake-remote.git"
    bare.mkdir()
    _git(["init", "--bare", "--initial-branch=main"], cwd=bare)

    # Seed via a temp clone so we get a real commit on main.
    seed = tmp_path / "_seed"
    seed.mkdir()
    _git(["clone", str(bare), str(seed)], cwd=tmp_path)
    (seed / "README.md").write_text("# fake repo\n\nseed line.\n")
    _git(["checkout", "-b", "main"], cwd=seed)
    _git(["-c", "user.name=Seeder", "-c", "user.email=s@x", "add", "README.md"], cwd=seed)
    _git(
        ["-c", "user.name=Seeder", "-c", "user.email=s@x", "commit", "-m", "seed"],
        cwd=seed,
    )
    _git(["push", "-u", "origin", "main"], cwd=seed)
    return bare


def _make_fake_gh(tmp_path: Path, log_file: Path | None = None) -> Path:
    """Drop a fake ``gh`` script that echoes a fake PR URL.

    If ``log_file`` is given, the script appends each invocation's
    argv (one per line) to it for assertion.
    """
    script = tmp_path / "bin" / "gh"
    script.parent.mkdir(parents=True, exist_ok=True)
    log_path = log_file or (tmp_path / "gh-calls.log")
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "$@" >> "{log_path}"
            if [ "$1" = "pr" ] && [ "$2" = "create" ]; then
              echo "https://github.com/owner/name/pull/42"
              exit 0
            fi
            if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
              echo '{{"url":"https://github.com/owner/name/pull/42","state":"OPEN","title":"t"}}'
              exit 0
            fi
            exit 0
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _make_provider(
    tmp_path: Path,
    *,
    repo: str = "owner/name",
    branch: str = "main",
    pr_branch_prefix: str = "agno",
    github_token: str | None = "fake-token",
) -> tuple[GitHubContextProvider, Path]:
    """Build a provider whose 'remote' is a local bare repo."""
    remote = _make_fake_remote(tmp_path)
    root = tmp_path / "repos"
    provider = GitHubContextProvider(
        repo=repo,
        root=root,
        branch=branch,
        pr_branch_prefix=pr_branch_prefix,
        github_token=github_token,
    )
    # Override the clone URL to point at the local bare remote — the
    # provider's _build_clone_url would otherwise try github.com.
    provider._build_clone_url = lambda: str(remote)  # type: ignore[method-assign]
    return provider, remote


# ---------------------------------------------------------------------------
# _parse_repo / _sanitize_task helpers
# ---------------------------------------------------------------------------


def test_parse_repo_owner_name():
    assert _parse_repo("agno-agi/scout") == ("agno-agi", "scout")


def test_parse_repo_https_url():
    assert _parse_repo("https://github.com/agno-agi/scout.git") == ("agno-agi", "scout")


def test_parse_repo_https_no_dot_git():
    assert _parse_repo("https://github.com/agno-agi/scout") == ("agno-agi", "scout")


def test_parse_repo_invalid_raises():
    with pytest.raises(ValueError, match="could not parse repo"):
        _parse_repo("not-a-repo")


def test_sanitize_task_simple():
    assert _sanitize_task("session-abc-123") == "session-abc-123"


def test_sanitize_task_strips_unsafe_chars():
    assert _sanitize_task("session/abc!@#xyz") == "session-abc-xyz"


def test_sanitize_task_caps_length():
    out = _sanitize_task("x" * 200)
    assert len(out) <= 40


def test_sanitize_task_empty_falls_back_to_uuid():
    out = _sanitize_task("!!!")
    assert out  # non-empty
    assert all(c.isalnum() or c in "-_" for c in out)


# ---------------------------------------------------------------------------
# Status — pre-setup, post-setup
# ---------------------------------------------------------------------------


def test_status_before_setup_reports_uninitialized(tmp_path: Path):
    p = GitHubContextProvider(repo="owner/name", root=tmp_path / "missing")
    s = p.status()
    assert s.ok is False
    assert "not initialized" in s.detail


def test_status_when_dir_exists_but_not_git(tmp_path: Path):
    workdir = tmp_path / "repos" / "owner" / "name"
    workdir.mkdir(parents=True)
    p = GitHubContextProvider(repo="owner/name", root=tmp_path / "repos")
    s = p.status()
    assert s.ok is False
    assert "not a git repo" in s.detail


@pytest.mark.asyncio
async def test_asetup_clones_fresh(tmp_path: Path):
    p, _ = _make_provider(tmp_path)
    assert not p.workdir.exists()
    await p.asetup()
    assert p.workdir.exists()
    assert (p.workdir / ".git").exists()
    assert (p.workdir / "README.md").read_text().startswith("# fake repo")
    s = p.status()
    assert s.ok is True
    assert "owner/name@main:" in s.detail


@pytest.mark.asyncio
async def test_asetup_idempotent(tmp_path: Path):
    p, _ = _make_provider(tmp_path)
    await p.asetup()
    sha_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=p.workdir, capture_output=True, text=True
    ).stdout.strip()
    await p.asetup()  # second call must not re-clone or break
    sha_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=p.workdir, capture_output=True, text=True
    ).stdout.strip()
    assert sha_before == sha_after


@pytest.mark.asyncio
async def test_asetup_dirty_tree_warns_no_fail(tmp_path: Path):
    p, remote = _make_provider(tmp_path)
    await p.asetup()

    # Dirty the local tree.
    (p.workdir / "README.md").write_text("dirty content (uncommitted)")

    # Push a new commit to the remote so the local branch is behind —
    # combined with the dirty tree, `pull --ff-only` will fail.
    pusher = tmp_path / "_pusher"
    subprocess.run(
        ["git", "clone", str(remote), str(pusher)],
        check=True,
        capture_output=True,
    )
    (pusher / "NEW.md").write_text("from remote\n")
    subprocess.run(
        ["git", "-c", "user.name=u", "-c", "user.email=u@x", "add", "NEW.md"],
        cwd=pusher,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=u",
            "-c",
            "user.email=u@x",
            "commit",
            "-m",
            "remote update",
        ],
        cwd=pusher,
        check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=pusher, check=True)

    # Second asetup must NOT raise even though pull --ff-only fails.
    await p.asetup()
    s = p.status()
    assert s.ok is True


@pytest.mark.asyncio
async def test_asetup_picks_up_token_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token-xyz")
    p, _ = _make_provider(tmp_path, github_token=None)
    await p.asetup()
    assert p.github_token == "env-token-xyz"


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------


def test_default_surface_is_query_plus_update(tmp_path: Path):
    p = GitHubContextProvider(repo="owner/name", root=tmp_path, id="ghx")
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_ghx", "update_ghx"]


def test_mode_tools_returns_read_only_surface(tmp_path: Path):
    p = GitHubContextProvider(repo="owner/name", root=tmp_path, id="ghx", mode=ContextMode.tools)
    tools = p.get_tools()
    # Two toolkits: Workspace (read-only aliases) + GitReadTools.
    # No update tool; no GitWriteTools.
    names = [getattr(t, "name", None) for t in tools]
    assert "workspace" in names
    assert "git_read_tools" in names
    assert "git_write_tools" not in names
    assert "update_ghx" not in names


# ---------------------------------------------------------------------------
# Worktree lifecycle — created on first update, reused per session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_creates_worktree_on_prefixed_branch(tmp_path: Path, monkeypatch):
    p, _ = _make_provider(tmp_path)
    await p.asetup()

    # Stub the write agent so we don't hit an LLM. We just need the
    # worktree creation side-effect.
    class _Stub:
        async def arun(self, _instruction, **_kwargs):
            class _Out:
                content = "ok"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    captured: dict = {}

    def _build(task_workdir):
        captured["task_workdir"] = task_workdir
        return _Stub()

    monkeypatch.setattr(p, "_build_write_agent", _build)

    from agno.run import RunContext

    rc = RunContext(run_id="r1", session_id="sess-abc")
    await p.aupdate("change something", run_context=rc)

    task_workdir = captured["task_workdir"]
    assert task_workdir.exists()
    assert task_workdir.is_relative_to(p.workdir)

    # The worktree's branch should match the prefix.
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=task_workdir,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "agno/sess-abc"


@pytest.mark.asyncio
async def test_update_reuses_worktree_for_same_session(tmp_path: Path, monkeypatch):
    p, _ = _make_provider(tmp_path)
    await p.asetup()

    paths: list[Path] = []

    class _Stub:
        async def arun(self, _instruction, **_kwargs):
            class _Out:
                content = "ok"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    def _build(task_workdir):
        paths.append(task_workdir)
        return _Stub()

    monkeypatch.setattr(p, "_build_write_agent", _build)

    from agno.run import RunContext

    rc = RunContext(run_id="r1", session_id="sess-x")
    await p.aupdate("first", run_context=rc)
    await p.aupdate("second", run_context=rc)

    # _build_write_agent should only have been called once — same session
    # reuses the cached agent.
    assert len(paths) == 1


@pytest.mark.asyncio
async def test_update_without_session_id_is_ephemeral(tmp_path: Path, monkeypatch):
    p, _ = _make_provider(tmp_path)
    await p.asetup()

    class _Stub:
        async def arun(self, _instruction, **_kwargs):
            class _Out:
                content = "ok"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    monkeypatch.setattr(p, "_build_write_agent", lambda _wd: _Stub())

    await p.aupdate("change something")  # no run_context → ephemeral

    # Worktree should be torn down post-call.
    assert p._task_workdirs == {}
    assert p._write_agents == {}


@pytest.mark.asyncio
async def test_aclose_removes_worktrees(tmp_path: Path, monkeypatch):
    p, _ = _make_provider(tmp_path)
    await p.asetup()

    class _Stub:
        async def arun(self, _instruction, **_kwargs):
            class _Out:
                content = "ok"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    monkeypatch.setattr(p, "_build_write_agent", lambda _wd: _Stub())

    from agno.run import RunContext

    rc = RunContext(run_id="r1", session_id="sess-cleanup")
    await p.aupdate("first", run_context=rc)
    assert p._task_workdirs

    await p.aclose()
    assert p._task_workdirs == {}
    # The worktree directory should be gone (or at least the branch).
    branches = subprocess.run(["git", "branch"], cwd=p.workdir, capture_output=True, text=True).stdout
    assert "agno/sess-cleanup" not in branches


@pytest.mark.asyncio
async def test_aclose_safe_without_setup(tmp_path: Path):
    p = GitHubContextProvider(repo="owner/name", root=tmp_path / "never-setup")
    # Must not raise even though asetup was never called.
    await p.aclose()


# ---------------------------------------------------------------------------
# GitReadTools — surface check
# ---------------------------------------------------------------------------


def test_git_read_tools_log_against_real_repo(tmp_path: Path):
    # Build a tiny real repo and assert git_log produces output.
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "--initial-branch=main"], cwd=repo)
    (repo / "a.txt").write_text("hi")
    _git(["-c", "user.name=u", "-c", "user.email=u@x", "add", "a.txt"], cwd=repo)
    _git(["-c", "user.name=u", "-c", "user.email=u@x", "commit", "-m", "first"], cwd=repo)

    tools = GitReadTools(workdir=repo)
    out = tools.git_log(n=5)
    assert "first" in out


# ---------------------------------------------------------------------------
# GitWriteTools — branch prefix safety + author identity
# ---------------------------------------------------------------------------


def _init_worktree(tmp_path: Path, prefix: str = "agno") -> tuple[Path, Path, Path]:
    """Make a workdir with a single 'agno/test' worktree branch ready for write tests."""
    bare = _make_fake_remote(tmp_path)
    workdir = tmp_path / "checkout"
    _git(["clone", str(bare), str(workdir)], cwd=tmp_path)
    task_workdir = workdir / "worktrees" / "test"
    branch_name = f"{prefix}/test"
    _git(
        ["worktree", "add", str(task_workdir), "-b", branch_name, "origin/main"],
        cwd=workdir,
    )
    return bare, workdir, task_workdir


def test_write_tools_rejects_non_prefixed_branch(tmp_path: Path):
    _, workdir, task_workdir = _init_worktree(tmp_path)
    tools = GitWriteTools(
        workdir=workdir,
        task_workdir=task_workdir,
        pr_branch_prefix="agno",
        base_branch="main",
    )
    out = tools.git_push(branch="main")
    assert "refusing to push" in out
    assert "agno/" in out


def test_write_tools_create_pull_request_validates_branch(tmp_path: Path):
    _, workdir, task_workdir = _init_worktree(tmp_path)
    tools = GitWriteTools(
        workdir=workdir,
        task_workdir=task_workdir,
        pr_branch_prefix="agno",
        base_branch="main",
    )
    out = tools.create_pull_request(title="t", body="b", branch="main")
    assert "refusing to push" in out


def test_write_tools_path_escape_rejected(tmp_path: Path):
    _, workdir, _ = _init_worktree(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    with pytest.raises(ValueError, match="not inside workdir"):
        GitWriteTools(
            workdir=workdir,
            task_workdir=other,
            pr_branch_prefix="agno",
            base_branch="main",
        )


def test_write_tools_commit_uses_per_call_author(tmp_path: Path):
    _, workdir, task_workdir = _init_worktree(tmp_path)
    tools = GitWriteTools(
        workdir=workdir,
        task_workdir=task_workdir,
        pr_branch_prefix="agno",
        base_branch="main",
    )
    # Add and commit a file. We don't set global git config — the
    # commit must succeed because the toolkit injects identity per call.
    (task_workdir / "x.txt").write_text("hello\n")
    add_out = tools.git_add(paths=["x.txt"])
    assert "Staged" in add_out
    commit_out = tools.git_commit(message="add x")
    assert commit_out.startswith("Committed "), commit_out

    # Verify the author identity is what we expected.
    log_out = subprocess.run(
        ["git", "log", "-1", "--pretty=%an <%ae>"],
        cwd=task_workdir,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert "Agno" in log_out
    assert "agent@agno.ai" in log_out


def test_write_tools_create_pull_request_invokes_gh(tmp_path: Path):
    _, workdir, task_workdir = _init_worktree(tmp_path)
    log = tmp_path / "gh.log"
    fake_gh = _make_fake_gh(tmp_path, log_file=log)

    tools = GitWriteTools(
        workdir=workdir,
        task_workdir=task_workdir,
        pr_branch_prefix="agno",
        base_branch="main",
        github_token="t-x",
        gh_path=str(fake_gh),
    )
    out = tools.create_pull_request(title="My PR", body="Body text")
    assert "https://github.com/owner/name/pull/42" in out
    log_lines = log.read_text().splitlines()
    assert any("pr create" in ln for ln in log_lines)
    assert any("--title My PR" in ln or "My PR" in ln for ln in log_lines)
    # Branch prefix safety stays in effect even with a fake gh — base
    # branch is "main", head is the worktree's prefixed branch.
    assert any("--base main" in ln for ln in log_lines)


def test_write_tools_pr_status_returns_json(tmp_path: Path):
    _, workdir, task_workdir = _init_worktree(tmp_path)
    fake_gh = _make_fake_gh(tmp_path)
    tools = GitWriteTools(
        workdir=workdir,
        task_workdir=task_workdir,
        pr_branch_prefix="agno",
        base_branch="main",
        gh_path=str(fake_gh),
    )
    out = tools.pr_status()
    assert "OPEN" in out
    assert "https://github.com/owner/name/pull/42" in out


def test_write_tools_create_pull_request_missing_gh(tmp_path: Path):
    _, workdir, task_workdir = _init_worktree(tmp_path)
    nonexistent = tmp_path / "no-such-gh"
    tools = GitWriteTools(
        workdir=workdir,
        task_workdir=task_workdir,
        pr_branch_prefix="agno",
        base_branch="main",
        gh_path=str(nonexistent),
    )
    out = tools.create_pull_request(title="t", body="b")
    assert "not found on PATH" in out


# ---------------------------------------------------------------------------
# Token sourcing
# ---------------------------------------------------------------------------


def test_token_sourcing_kwarg_wins(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    p = GitHubContextProvider(repo="owner/name", root=tmp_path, github_token="kwarg-token")
    # Constructor keeps kwarg; asetup() would fall back to env if None.
    assert p.github_token == "kwarg-token"


@pytest.mark.asyncio
async def test_token_sourcing_env_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    p, _ = _make_provider(tmp_path, github_token=None)
    await p.asetup()
    assert p.github_token == "env-token"


# ---------------------------------------------------------------------------
# Read agent build — sanity check tools are wired
# ---------------------------------------------------------------------------


def test_read_agent_has_workspace_and_git_read_tools(tmp_path: Path):
    p, _ = _make_provider(tmp_path)
    # Build the agent without running setup — read agent only needs the
    # paths to be present at run time, not at build time.
    p.workdir.mkdir(parents=True, exist_ok=True)
    agent = p._ensure_read_agent()
    tool_names = {getattr(t, "name", None) for t in agent.tools or []}
    assert "workspace" in tool_names
    assert "git_read_tools" in tool_names
