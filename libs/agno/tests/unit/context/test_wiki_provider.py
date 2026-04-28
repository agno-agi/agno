"""Unit tests for WikiContextProvider, FileSystemBackend, and GitBackend.

These don't hit GitHub. The git backend tests stub `git_ops.run` so we
can assert on the args + scrubber wiring without a real subprocess.
The provider round-trip stubs the sub-agents so it doesn't hit a model.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agno.context.mode import ContextMode
from agno.context.wiki import (
    FileSystemBackend,
    GitBackend,
    WikiBackendError,
    WikiContextProvider,
)
from agno.context.wiki.backend import _count_changed_files, _normalise_remote, _remotes_equivalent
from agno.context.wiki.git_ops import (
    GitError,
    GitResult,
    Scrubber,
    build_authenticated_url,
)

# ---------------------------------------------------------------------------
# Scrubber
# ---------------------------------------------------------------------------


def test_scrubber_replaces_registered_secret():
    s = Scrubber()
    s.add("ghp_supersecret")
    out = s.scrub("error: token=ghp_supersecret was rejected")
    assert "ghp_supersecret" not in out
    assert "***" in out


def test_scrubber_handles_empty_input():
    s = Scrubber()
    s.add("ghp_supersecret")
    assert s.scrub("") == ""
    assert s.scrub(None) is None  # type: ignore[arg-type]


def test_scrubber_ignores_empty_secret():
    s = Scrubber()
    s.add("")
    s.add(None)
    # Nothing to scrub but also no crash.
    assert s.scrub("hello world") == "hello world"


def test_scrubber_catches_unregistered_xaccess_url():
    s = Scrubber()
    # Even without registering this exact URL, the regex catch-all
    # blocks any `x-access-token:<token>@` form from leaking.
    leaked = "fatal: unable to access 'https://x-access-token:ghp_other@github.com/o/r.git/'"
    out = s.scrub(leaked)
    assert "ghp_other" not in out
    assert "x-access-token:***@" in out


def test_scrubber_handles_multiple_registered_secrets():
    s = Scrubber()
    s.add("token-a")
    s.add("token-b")
    out = s.scrub("a=token-a b=token-b c=plain")
    assert "token-a" not in out
    assert "token-b" not in out
    assert "plain" in out


# ---------------------------------------------------------------------------
# build_authenticated_url
# ---------------------------------------------------------------------------


def test_build_authenticated_url_embeds_token():
    url = build_authenticated_url("https://github.com/owner/repo.git", "ghp_x")
    assert url == "https://x-access-token:ghp_x@github.com/owner/repo.git"


def test_build_authenticated_url_strips_existing_credentials():
    # If a caller passes back the previously authenticated URL, we
    # shouldn't double-stack credentials.
    pre = "https://x-access-token:OLD@github.com/owner/repo.git"
    url = build_authenticated_url(pre, "NEW")
    assert url == "https://x-access-token:NEW@github.com/owner/repo.git"


def test_build_authenticated_url_rejects_ssh():
    with pytest.raises(ValueError, match="HTTPS"):
        build_authenticated_url("git@github.com:owner/repo.git", "ghp_x")


def test_build_authenticated_url_requires_token():
    with pytest.raises(ValueError, match="PAT is required"):
        build_authenticated_url("https://github.com/owner/repo.git", "")


def test_build_authenticated_url_rejects_non_https():
    with pytest.raises(ValueError, match="https"):
        build_authenticated_url("http://github.com/owner/repo.git", "ghp_x")


# ---------------------------------------------------------------------------
# Remote normalisation
# ---------------------------------------------------------------------------


def test_normalise_remote_strips_dot_git_and_credentials():
    a = "https://x-access-token:abc@github.com/owner/repo.git"
    b = "https://github.com/owner/repo"
    assert _normalise_remote(a) == _normalise_remote(b)
    assert _remotes_equivalent(a, b) is True


def test_normalise_remote_distinct_repos_not_equivalent():
    assert (
        _remotes_equivalent(
            "https://github.com/owner/repo-a.git",
            "https://github.com/owner/repo-b.git",
        )
        is False
    )


# ---------------------------------------------------------------------------
# _count_changed_files
# ---------------------------------------------------------------------------


def test_count_changed_files_uses_summary_line():
    stat = "docs/a.md | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)"
    assert _count_changed_files(stat) == 1
    multi = "docs/a.md | 2 +-\ndocs/b.md | 4 ++--\n 2 files changed, 3 insertions(+), 3 deletions(-)"
    assert _count_changed_files(multi) == 2


def test_count_changed_files_falls_back_to_body_count():
    # No summary line — just count rows that look like file entries.
    stat = "docs/a.md | 2 +-\ndocs/b.md | 1 +\n"
    assert _count_changed_files(stat) == 2


# ---------------------------------------------------------------------------
# FileSystemBackend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filesystem_backend_setup_creates_directory(tmp_path: Path):
    target = tmp_path / "wiki"
    fs = FileSystemBackend(path=target)
    await fs.setup()
    assert target.is_dir()


@pytest.mark.asyncio
async def test_filesystem_backend_sync_and_commit_are_noops(tmp_path: Path):
    fs = FileSystemBackend(path=tmp_path)
    await fs.sync()  # must not raise
    assert await fs.commit_after_write() is None


def test_filesystem_backend_status_ok_for_directory(tmp_path: Path):
    fs = FileSystemBackend(path=tmp_path)
    status = fs.status()
    assert status.ok is True
    assert str(tmp_path) in status.detail


def test_filesystem_backend_status_reports_missing(tmp_path: Path):
    fs = FileSystemBackend(path=tmp_path / "missing")
    status = fs.status()
    assert status.ok is False
    assert "does not exist" in status.detail


def test_filesystem_backend_status_reports_non_directory(tmp_path: Path):
    f = tmp_path / "not-a-dir"
    f.write_text("hello")
    fs = FileSystemBackend(path=f)
    status = fs.status()
    assert status.ok is False
    assert "not a directory" in status.detail


# ---------------------------------------------------------------------------
# WikiContextProvider — surface and round-trip
# ---------------------------------------------------------------------------


def test_provider_default_surface_is_query_plus_update(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_wiki", "update_wiki"]


def test_provider_custom_id_renames_tools(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), id="docs")
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_docs", "update_docs"]


def test_provider_write_false_drops_update_tool(tmp_path: Path):
    """Voice-folder pattern: read+write provider configured read-only."""
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), id="voice", write=False)
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_voice"]


def test_provider_read_false_drops_query_tool(tmp_path: Path):
    """Asymmetric write-only sink — rare but supported."""
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), id="sink", read=False)
    tools = p.get_tools()
    assert [t.name for t in tools] == ["update_sink"]


def test_provider_both_flags_false_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="at least one of `read` or `write`"):
        WikiContextProvider(backend=FileSystemBackend(path=tmp_path), read=False, write=False)


def test_provider_instructions_omit_update_when_write_false(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), id="voice", write=False)
    text = p.instructions()
    assert "query_voice" in text
    assert "update_voice" not in text


def test_provider_tools_mode_is_read_only(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), mode=ContextMode.tools)
    workspace = p.get_tools()[0]
    # Only the read aliases should be registered — no write/edit/delete.
    assert sorted(workspace.functions.keys()) == ["list_files", "read_file", "search_content"]


def test_provider_tools_mode_instructions_call_out_read_only(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), mode=ContextMode.tools)
    text = p.instructions()
    assert "read-only" in text
    assert "mode=default" in text


def test_provider_status_forwards_from_backend(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path / "nope"))
    status = p.status()
    assert status.ok is False
    assert "does not exist" in status.detail


@pytest.mark.asyncio
async def test_provider_round_trip_with_filesystem_backend(tmp_path: Path):
    """update -> commit hook -> query, with stubbed sub-agents.

    The point is the wiring: aupdate must hit the write agent, commit
    hook fires on the backend (no-op for FS), aquery must hit the
    read agent. We stub both agents so no model is hit.
    """
    p = WikiContextProvider(
        id="wiki",
        backend=FileSystemBackend(path=tmp_path),
    )

    write_calls: list[str] = []
    read_calls: list[str] = []
    commit_calls: list[bool] = []

    class _StubAgent:
        def __init__(self, sink: list[str], reply: str) -> None:
            self._sink = sink
            self._reply = reply

        async def arun(self, message: str, **kwargs):  # noqa: ANN001
            self._sink.append(message)

            class _Out:
                content = self._reply  # noqa: B023

                def get_content_as_string(self):
                    return self.content

            return _Out()

    p._write_agent = _StubAgent(write_calls, "wrote runbooks/deploys.md")
    p._read_agent = _StubAgent(read_calls, "deploys.md says: deploy on green")

    # Spy on the backend hook so we know it was awaited inside the lock.
    original_commit = p.backend.commit_after_write

    async def _spy_commit(*, model=None):  # noqa: ANN001
        commit_calls.append(True)
        return await original_commit(model=model)

    p.backend.commit_after_write = _spy_commit  # type: ignore[assignment]

    out_w = await p.aupdate("add a deploys runbook")
    out_r = await p.aquery("what does the deploys runbook say?")

    assert write_calls == ["add a deploys runbook"]
    assert read_calls == ["what does the deploys runbook say?"]
    assert commit_calls == [True]
    # FS backend returns None from commit hook -> no commit note appended.
    assert "wrote runbooks/deploys.md" in (out_w.text or "")
    assert "deploys.md says: deploy on green" in (out_r.text or "")


@pytest.mark.asyncio
async def test_provider_query_tool_does_not_acquire_lock(tmp_path: Path):
    """A scheduled sync() in flight must not block reads."""
    import asyncio

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))

    class _StubAgent:
        async def arun(self, message: str, **kwargs):  # noqa: ANN001
            class _Out:
                content = "ok"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    p._read_agent = _StubAgent()

    async with p._git_lock:
        # If aquery tried to take the lock, this would deadlock.
        out = await asyncio.wait_for(p.aquery("anything"), timeout=2.0)
    assert out.text == "ok"


@pytest.mark.asyncio
async def test_provider_sync_acquires_lock_and_delegates(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))

    sync_calls = {"n": 0}

    async def _recording_sync():
        sync_calls["n"] += 1

    p.backend.sync = _recording_sync  # type: ignore[assignment]

    await p.sync()
    assert sync_calls["n"] == 1
    # Lock must be released when sync returns.
    assert not p._git_lock.locked()


# ---------------------------------------------------------------------------
# GitBackend — construction safety + token scrubbing
# ---------------------------------------------------------------------------


def test_git_backend_requires_token():
    with pytest.raises(ValueError, match="github_token is required"):
        GitBackend(repo_url="https://github.com/o/r.git", github_token="")


def test_git_backend_requires_repo_url():
    with pytest.raises(ValueError, match="repo_url is required"):
        GitBackend(repo_url="", github_token="ghp_x")


def test_git_backend_authenticated_url_is_built_once_and_registered():
    b = GitBackend(repo_url="https://github.com/owner/repo.git", github_token="ghp_x")
    assert b._authenticated_url == "https://x-access-token:ghp_x@github.com/owner/repo.git"
    # Both the bare token and the full URL should be in the scrubber so a
    # leak in either form gets stripped.
    assert "ghp_x" in b._scrubber.secrets
    assert b._authenticated_url in b._scrubber.secrets


def test_git_backend_default_local_path_under_repos():
    b = GitBackend(repo_url="https://github.com/owner/My.Repo.git", github_token="ghp_x")
    # `/repos/<sanitized>` per the spec.
    assert b.path == Path("/repos/my-repo")


def test_git_backend_custom_local_path_is_resolved(tmp_path: Path):
    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_x",
        local_path=tmp_path / "wiki",
    )
    assert b.path == (tmp_path / "wiki").resolve()


@pytest.mark.asyncio
async def test_git_backend_scrubs_token_from_subprocess_errors(monkeypatch, tmp_path: Path):
    """Force a GitError and assert the scrubber stripped the token from stderr."""
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_supersecret",
        local_path=tmp_path / "clone",
    )

    async def _fake_run(args, *, cwd, scrubber=None, **kwargs):  # noqa: ANN001
        # Mirrors what `git_ops.run` does on a non-zero exit: scrub
        # both args and stderr before constructing the GitError. Args
        # need scrubbing because `git clone <authenticated-url> ...`
        # carries the PAT.
        leaked = f"fatal: unable to access '{b._authenticated_url}/': the requested token ghp_supersecret was rejected"
        if scrubber is not None:
            safe_args = [scrubber.scrub(a) for a in args]
            stderr = scrubber.scrub(leaked)
        else:
            safe_args = list(args)
            stderr = leaked
        raise GitError(safe_args, 128, stderr)

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    with pytest.raises(GitError) as excinfo:
        await b.setup()

    msg = str(excinfo.value)
    assert "ghp_supersecret" not in msg
    assert "ghp_supersecret" not in excinfo.value.stderr
    assert "***" in msg


@pytest.mark.asyncio
async def test_git_backend_existing_clone_wrong_remote_raises_by_default(monkeypatch, tmp_path: Path):
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_x",
        local_path=tmp_path / "clone",
    )
    # Set up the local "clone" with a stub `.git` so setup() takes the
    # existing-clone branch.
    b.path.mkdir(parents=True)
    (b.path / ".git").mkdir()

    async def _fake_run(args, *, cwd, scrubber=None, check=True, **kwargs):  # noqa: ANN001
        if args[:3] == ["remote", "get-url", "origin"]:
            return GitResult(returncode=0, stdout="https://github.com/other/repo.git\n", stderr="")
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    with pytest.raises(WikiBackendError, match="force_clone=True"):
        await b.setup()


@pytest.mark.asyncio
async def test_git_backend_existing_clone_force_clone_wipes_and_reclones(monkeypatch, tmp_path: Path):
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_x",
        local_path=tmp_path / "clone",
        force_clone=True,
    )
    # Existing clone with mismatched remote.
    b.path.mkdir(parents=True)
    (b.path / ".git").mkdir()
    (b.path / "stale-file.md").write_text("stale")

    invocations: list[list[str]] = []

    async def _fake_run(args, *, cwd, scrubber=None, check=True, **kwargs):  # noqa: ANN001
        invocations.append(list(args))
        if args[:3] == ["remote", "get-url", "origin"]:
            return GitResult(returncode=0, stdout="https://github.com/other/repo.git\n", stderr="")
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    await b.setup()

    # The stale clone was wiped and a fresh `git clone` was issued.
    assert any(args[0] == "clone" for args in invocations), (
        f"expected git clone to be invoked after wipe; saw {invocations}"
    )
    # Identity gets configured after the clone.
    assert any(args[0] == "config" and args[1] == "user.name" for args in invocations)


@pytest.mark.asyncio
async def test_git_backend_commit_after_write_returns_none_when_nothing_staged(monkeypatch, tmp_path: Path):
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_x",
        local_path=tmp_path / "clone",
    )
    b.path.mkdir(parents=True)

    seen: list[list[str]] = []

    async def _fake_run(args, *, cwd, scrubber=None, check=True, **kwargs):  # noqa: ANN001
        seen.append(list(args))
        if args[:3] == ["diff", "--cached", "--quiet"]:
            # Exit 0 == no staged changes.
            return GitResult(returncode=0, stdout="", stderr="")
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    summary = await b.commit_after_write()
    assert summary is None
    # The no-op path still attempts a push so any commits left over from a
    # previous failed push get flushed once auth recovers. `git push` with
    # nothing to send is a cheap no-op.
    assert ["push", "origin", "main"] in seen


@pytest.mark.asyncio
async def test_git_backend_idle_push_failure_is_swallowed(monkeypatch, tmp_path: Path):
    """When nothing is staged, a failing idle push must not propagate."""
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_x",
        local_path=tmp_path / "clone",
    )
    b.path.mkdir(parents=True)

    async def _fake_run(args, *, cwd, scrubber=None, check=True, **kwargs):  # noqa: ANN001
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return GitResult(returncode=0, stdout="", stderr="")
        if args[:1] == ["push"]:
            from agno.context.wiki.git_ops import GitError

            raise GitError(args=args, returncode=128, stderr="403")
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    summary = await b.commit_after_write()
    assert summary is None  # idle path, push failure swallowed


@pytest.mark.asyncio
async def test_git_backend_commit_after_write_uses_fallback_message_without_model(monkeypatch, tmp_path: Path):
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token="ghp_x",
        local_path=tmp_path / "clone",
    )
    b.path.mkdir(parents=True)

    seen: dict[str, list[str]] = {"commit_msg": []}

    async def _fake_run(args, *, cwd, scrubber=None, check=True, **kwargs):  # noqa: ANN001
        if args[:3] == ["diff", "--cached", "--quiet"]:
            # Exit 1 == staged changes pending.
            return GitResult(returncode=1, stdout="", stderr="")
        if args[:3] == ["diff", "--cached", "--stat"]:
            return GitResult(
                returncode=0, stdout="docs/a.md | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)", stderr=""
            )
        if args[:3] == ["diff", "--cached"]:
            return GitResult(returncode=0, stdout="diff --git a/docs/a.md b/docs/a.md\n+hi\n", stderr="")
        if args[:1] == ["commit"]:
            # Capture the message the backend used.
            assert args[1] == "-m"
            seen["commit_msg"].append(args[2])
            return GitResult(returncode=0, stdout="", stderr="")
        if args[:1] == ["rev-parse"]:
            return GitResult(returncode=0, stdout="deadbeefcafe1234\n", stderr="")
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    summary = await b.commit_after_write(model=None)
    assert summary is not None
    assert summary.sha.startswith("deadbeef")
    assert summary.files_changed == 1
    # No model -> deterministic fallback prefix.
    assert seen["commit_msg"][0].startswith("Update wiki (")


# ---------------------------------------------------------------------------
# git_ops.run — happy path + GIT_TERMINAL_PROMPT enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_git_run_sets_terminal_prompt_zero(monkeypatch, tmp_path: Path):
    """Ensure the wrapper always sets GIT_TERMINAL_PROMPT=0 so a busted
    PAT fails fast instead of hanging on stdin."""
    import agno.context.wiki.git_ops as git_ops

    captured_env: dict[str, str] = {}

    class _FakeProc:
        def __init__(self) -> None:
            self.returncode = 0

        async def communicate(self):
            return (b"", b"")

        def kill(self):  # pragma: no cover - timeout path not exercised here
            pass

        async def wait(self):  # pragma: no cover
            pass

    async def _fake_exec(*args, env=None, **kwargs):  # noqa: ANN001
        captured_env.update(env or {})
        return _FakeProc()

    monkeypatch.setattr(git_ops.asyncio, "create_subprocess_exec", _fake_exec)

    await git_ops.run(["status"], cwd=tmp_path)
    assert captured_env.get("GIT_TERMINAL_PROMPT") == "0"


# ---------------------------------------------------------------------------
# Sanity: provider tool wrappers serialise Answer correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_query_tool_serialises_answer(tmp_path: Path):
    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))

    class _StubAgent:
        async def arun(self, message: str, **kwargs):  # noqa: ANN001
            class _Out:
                content = "hello"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    p._read_agent = _StubAgent()
    tool = next(t for t in p.get_tools() if t.name == "query_wiki")
    out = await tool.entrypoint(question="anything")
    payload = json.loads(out)
    assert payload == {"text": "hello"}


@pytest.mark.asyncio
async def test_web_backend_tools_attached_to_write_sub_agent(tmp_path: Path):
    """When `web` is wired, the write sub-agent gets web tools too."""
    from agno.context.backend import ContextBackend
    from agno.context.provider import Status as _Status
    from agno.tools import tool

    @tool(name="web_search")
    async def _web_search(query: str) -> str:
        return "{}"

    @tool(name="web_fetch")
    async def _web_fetch(url: str) -> str:
        return "{}"

    class _StubWeb(ContextBackend):
        def status(self) -> _Status:
            return _Status(ok=True, detail="stub")

        async def astatus(self) -> _Status:
            return self.status()

        def get_tools(self) -> list:
            return [_web_search, _web_fetch]

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), web=_StubWeb())
    write_agent = p._ensure_write_agent()
    tool_names = [getattr(t, "name", None) for t in write_agent.tools or []]
    assert "web_search" in tool_names
    assert "web_fetch" in tool_names
    # Workspace toolkit registers methods, not tool names — but it
    # must still be in the list (name attribute on Toolkit instances).
    assert any(getattr(t, "name", "") == "workspace" for t in write_agent.tools or [])


@pytest.mark.asyncio
async def test_web_backend_not_attached_to_read_sub_agent(tmp_path: Path):
    """The read sub-agent stays scoped to the wiki even with web wired."""
    from agno.context.backend import ContextBackend
    from agno.context.provider import Status as _Status
    from agno.tools import tool

    @tool(name="web_search")
    async def _web_search(query: str) -> str:
        return "{}"

    class _StubWeb(ContextBackend):
        def status(self) -> _Status:
            return _Status(ok=True, detail="stub")

        async def astatus(self) -> _Status:
            return self.status()

        def get_tools(self) -> list:
            return [_web_search]

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), web=_StubWeb())
    read_agent = p._ensure_read_agent()
    tool_names = [getattr(t, "name", None) for t in read_agent.tools or []]
    assert "web_search" not in tool_names


@pytest.mark.asyncio
async def test_web_backend_asetup_aclose_forwarded(tmp_path: Path):
    """Lifecycle hooks must reach the web backend (matters for MCP sessions)."""
    from agno.context.backend import ContextBackend
    from agno.context.provider import Status as _Status

    calls = {"asetup": 0, "aclose": 0}

    class _LifecycleWeb(ContextBackend):
        def status(self) -> _Status:
            return _Status(ok=True, detail="lifecycle")

        async def astatus(self) -> _Status:
            return self.status()

        def get_tools(self) -> list:
            return []

        async def asetup(self) -> None:
            calls["asetup"] += 1

        async def aclose(self) -> None:
            calls["aclose"] += 1

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), web=_LifecycleWeb())
    await p.asetup()
    assert calls["asetup"] == 1
    # asetup is idempotent — second call is a no-op on the provider,
    # which means the web backend isn't double-set-up either.
    await p.asetup()
    assert calls["asetup"] == 1
    await p.aclose()
    assert calls["aclose"] == 1


def test_web_none_keeps_default_write_instructions(tmp_path: Path):
    """No web backend = no ingestion stanza in the write sub-agent's prompt."""
    from agno.context.wiki.provider import WIKI_WEB_INGEST_INSTRUCTIONS

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))
    composed = p._compose_write_instructions()
    assert WIKI_WEB_INGEST_INSTRUCTIONS not in composed


def test_web_set_appends_ingestion_stanza(tmp_path: Path):
    from agno.context.backend import ContextBackend
    from agno.context.provider import Status as _Status
    from agno.context.wiki.provider import WIKI_WEB_INGEST_INSTRUCTIONS

    class _StubWeb(ContextBackend):
        def status(self) -> _Status:
            return _Status(ok=True, detail="stub")

        async def astatus(self) -> _Status:
            return self.status()

        def get_tools(self) -> list:
            return []

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), web=_StubWeb())
    composed = p._compose_write_instructions()
    assert WIKI_WEB_INGEST_INSTRUCTIONS in composed


def test_instructions_default_mode_advertises_web_when_wired(tmp_path: Path):
    from agno.context.backend import ContextBackend
    from agno.context.provider import Status as _Status

    class _StubWeb(ContextBackend):
        def status(self) -> _Status:
            return _Status(ok=True, detail="stub")

        async def astatus(self) -> _Status:
            return self.status()

        def get_tools(self) -> list:
            return []

    p_no_web = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))
    assert "fetch the web" not in p_no_web.instructions()

    p_web = WikiContextProvider(backend=FileSystemBackend(path=tmp_path), web=_StubWeb())
    assert "fetch the web" in p_web.instructions()


@pytest.mark.asyncio
async def test_provider_threads_run_context_into_sub_agents(tmp_path: Path):
    """user_id / session_id / metadata / dependencies must propagate."""
    from agno.run import RunContext

    p = WikiContextProvider(backend=FileSystemBackend(path=tmp_path))
    p._read_agent = type("M", (), {"arun": AsyncMock()})()
    out = type("Out", (), {"content": "ok", "get_content_as_string": lambda self: "ok"})()
    p._read_agent.arun.return_value = out  # type: ignore[attr-defined]

    rc = RunContext(
        run_id="r-1",
        user_id="u-7",
        session_id="s-7",
        metadata={"action_token": "xoxa-x"},
        dependencies={"tenant": "acme"},
    )
    await p.aquery("hello", run_context=rc)

    p._read_agent.arun.assert_awaited_once()  # type: ignore[attr-defined]
    _, kwargs = p._read_agent.arun.call_args  # type: ignore[attr-defined]
    assert kwargs == {
        "user_id": "u-7",
        "session_id": "s-7",
        "metadata": {"action_token": "xoxa-x"},
        "dependencies": {"tenant": "acme"},
    }
