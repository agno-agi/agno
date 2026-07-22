"""Credential-handling tests for GitBackend.

The PAT must never reach disk (`.git/config`) or argv: auth is injected
per remote-facing git call through an ephemeral credential helper in the
subprocess environment (`GitBackend._git_env`). Tests here run against a
local bare repo over `file://` (offline, no real PAT) plus direct
assertions on the injected environment. `file://` transports never
consult credential helpers, so the round-trip test proves push works
with a bare origin, while the env/helper tests prove the injection
contents.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agno.context.wiki import GitBackend
from agno.context.wiki.backend import _GIT_CREDENTIAL_HELPER
from agno.context.wiki.git_ops import GitResult

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

TOKEN = "ghp_supersecret"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _isolated_git_config(tmp_path_factory, monkeypatch):
    # Keep the developer's global/system git config (gpg signing, hook
    # templates, stored credential helpers) out of the subprocesses.
    cfg = tmp_path_factory.mktemp("gitcfg") / "gitconfig"
    cfg.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture()
def bare_remote(tmp_path: Path) -> Path:
    """Local bare repo with one commit on `main`, reachable over file://."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(["init", "--initial-branch=main"], seed)
    _git(["config", "user.name", "Seed"], seed)
    _git(["config", "user.email", "seed@example.com"], seed)
    (seed / "readme.md").write_text("# wiki\n")
    _git(["add", "-A"], seed)
    _git(["commit", "-m", "seed"], seed)
    remote = tmp_path / "remote.git"
    _git(["clone", "--bare", str(seed), str(remote)], tmp_path)
    return remote


# ---------------------------------------------------------------------------
# _git_env / credential helper contents
# ---------------------------------------------------------------------------


def test_git_env_contents(tmp_path: Path):
    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )
    env = b._git_env()
    assert env["GIT_CONFIG_COUNT"] == "5"
    # Entry 0 resets any system/global helper so a stored identity
    # (e.g. osxkeychain) cannot answer instead of the injected token.
    assert env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_0"] == ""
    assert env["GIT_CONFIG_KEY_1"] == "credential.helper"
    helper = env["GIT_CONFIG_VALUE_1"]
    assert "username=x-access-token" in helper
    assert "password=%s" in helper
    assert "$AGNO_GIT_TOKEN" in helper
    assert TOKEN not in helper
    assert env["GIT_CONFIG_KEY_2"] == "credential.useHttpPath"
    assert env["GIT_CONFIG_VALUE_2"] == "true"
    # Entries 3-4 pin repo_url to itself so a caller url.<prefix>.insteadOf
    # cannot reroute the operation off the credential-injected transport.
    assert env["GIT_CONFIG_KEY_3"] == "url.https://github.com/owner/repo.git.insteadOf"
    assert env["GIT_CONFIG_VALUE_3"] == "https://github.com/owner/repo.git"
    assert env["GIT_CONFIG_KEY_4"] == "url.https://github.com/owner/repo.git.pushInsteadOf"
    assert env["GIT_CONFIG_VALUE_4"] == "https://github.com/owner/repo.git"
    assert env["AGNO_GIT_TOKEN"] == TOKEN
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_credential_helper_emits_username_and_password():
    # Execute the helper the way git does: shell fragment with the
    # credential action appended as $1.
    script = _GIT_CREDENTIAL_HELPER.lstrip("!") + ' "$@"'
    out = subprocess.run(
        ["sh", "-c", script, "agno-cred-helper", "get"],
        env={**os.environ, "AGNO_GIT_TOKEN": TOKEN},
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert out.stdout.splitlines() == [
        "username=x-access-token",
        f"password={TOKEN}",
    ]


def test_credential_helper_is_silent_and_zero_for_store():
    script = _GIT_CREDENTIAL_HELPER.lstrip("!") + ' "$@"'
    out = subprocess.run(
        ["sh", "-c", script, "agno-cred-helper", "store"],
        env={**os.environ, "AGNO_GIT_TOKEN": TOKEN},
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert out.stdout == ""


def test_git_backend_accepts_file_remote(tmp_path: Path):
    b = GitBackend(
        repo_url="file:///somewhere/wiki.git",
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )
    # No https form to scrub; the token itself is still registered.
    assert b._authenticated_url is None
    assert TOKEN in b._scrubber.secrets


# ---------------------------------------------------------------------------
# env forwarding at the remote-facing call sites (stubbed git)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_git_calls_inject_env_and_bare_url(monkeypatch, tmp_path: Path):
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )

    calls: list[tuple[list[str], dict | None]] = []

    async def _fake_run(args, *, cwd, scrubber=None, check=True, env=None, **kwargs):  # noqa: ANN001
        calls.append((list(args), env))
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    await b.setup()  # fresh path -> clone
    await b.sync()  # pull --rebase
    await b.commit_after_write()  # nothing staged -> idle push

    # The token must never ride on argv.
    for args, _ in calls:
        assert all(TOKEN not in a for a in args)

    remote_calls = [(args, env) for args, env in calls if args[0] in {"clone", "pull", "push"}]
    assert {args[0] for args, _ in remote_calls} == {"clone", "pull", "push"}
    for args, env in remote_calls:
        assert env is not None, f"remote op {args} missing credential env"
        assert env["AGNO_GIT_TOKEN"] == TOKEN
        assert env["GIT_CONFIG_COUNT"] == "5"

    clone_args = next(args for args, _ in calls if args[0] == "clone")
    assert "https://github.com/owner/repo.git" in clone_args

    set_url_calls = [args for args, _ in calls if args[:3] == ["remote", "set-url", "origin"]]
    assert set_url_calls, "clone path must normalise origin to the bare URL"
    assert all(args[3] == "https://github.com/owner/repo.git" for args in set_url_calls)


@pytest.mark.asyncio
async def test_staged_commit_pull_and_push_inject_env_and_bare_origin(monkeypatch, tmp_path: Path):
    # Companion to the test above: there `diff --cached --quiet` reports
    # nothing staged, so only the idle-push branch runs. Here the diff
    # check returns 1 (changes staged) so the commit -> rebase -> push
    # sequence runs, and the staged-path pull/push must carry the
    # credential env and address the bare `origin` remote.
    import agno.context.wiki.backend as backend_module

    b = GitBackend(
        repo_url="https://github.com/owner/repo.git",
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )

    sha = "0123456789abcdef0123456789abcdef01234567"
    stat = " notes.md | 2 ++\n 1 file changed, 2 insertions(+)\n"
    calls: list[tuple[list[str], dict | None]] = []

    async def _fake_run(args, *, cwd, scrubber=None, check=True, env=None, **kwargs):  # noqa: ANN001
        args = list(args)
        calls.append((args, env))
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return GitResult(returncode=1, stdout="", stderr="")
        if args[:3] == ["diff", "--cached", "--stat"]:
            return GitResult(returncode=0, stdout=stat, stderr="")
        if args[:2] == ["rev-parse", "HEAD"]:
            return GitResult(returncode=0, stdout=sha + "\n", stderr="")
        return GitResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend_module, "git_run", _fake_run)

    summary = await b.commit_after_write(model=None)

    assert summary is not None
    assert summary.sha == sha
    assert summary.files_changed == 1

    # The token must never ride on argv.
    for args, _ in calls:
        assert all(TOKEN not in a for a in args)

    pull_calls = [(args, env) for args, env in calls if args[0] == "pull"]
    push_calls = [(args, env) for args, env in calls if args[0] == "push"]
    assert [args for args, _ in pull_calls] == [["pull", "--rebase", "origin", "main"]]
    assert [args for args, _ in push_calls] == [["push", "origin", "main"]]
    for args, env in pull_calls + push_calls:
        assert env is not None, f"remote op {args} missing credential env"
        assert env["AGNO_GIT_TOKEN"] == TOKEN
        assert env["GIT_CONFIG_COUNT"] == "5"
        assert env["GIT_CONFIG_VALUE_1"] == _GIT_CREDENTIAL_HELPER

    first_args = [args[0] for args, _ in calls]
    assert first_args.index("commit") < first_args.index("pull") < first_args.index("push")


# ---------------------------------------------------------------------------
# real git against a local bare remote
# ---------------------------------------------------------------------------


@requires_git
@pytest.mark.asyncio
async def test_setup_leaves_no_token_on_disk(bare_remote: Path, tmp_path: Path):
    b = GitBackend(
        repo_url=bare_remote.as_uri(),
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )
    await b.setup()

    config_text = (b.path / ".git" / "config").read_text()
    assert TOKEN not in config_text
    assert "x-access-token" not in config_text
    origin = _git(["remote", "get-url", "origin"], b.path).stdout.strip()
    assert origin == b.repo_url


@requires_git
@pytest.mark.asyncio
async def test_commit_after_write_pushes_with_bare_origin(bare_remote: Path, tmp_path: Path):
    b = GitBackend(
        repo_url=bare_remote.as_uri(),
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )
    await b.setup()
    before = _git(["rev-parse", "main"], bare_remote).stdout.strip()

    (b.path / "notes.md").write_text("# Notes\n\nadded by test\n")
    summary = await b.commit_after_write(model=None)

    assert summary is not None
    assert summary.files_changed == 1
    after = _git(["rev-parse", "main"], bare_remote).stdout.strip()
    assert after != before
    assert after == summary.sha
    config_text = (b.path / ".git" / "config").read_text()
    assert TOKEN not in config_text


@requires_git
@pytest.mark.asyncio
async def test_setup_migrates_token_bearing_origin(bare_remote: Path, tmp_path: Path):
    b = GitBackend(
        repo_url=bare_remote.as_uri(),
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )
    await b.setup()

    # Simulate a clone left behind by an older version that persisted
    # the credential-bearing URL in .git/config.
    tainted = f"file://x-access-token:{TOKEN}@{bare_remote}"
    _git(["remote", "set-url", "origin", tainted], b.path)
    assert TOKEN in (b.path / ".git" / "config").read_text()

    await b.setup()

    config_text = (b.path / ".git" / "config").read_text()
    assert TOKEN not in config_text
    assert "x-access-token" not in config_text
    origin = _git(["remote", "get-url", "origin"], b.path).stdout.strip()
    assert origin == b.repo_url


@requires_git
@pytest.mark.asyncio
async def test_setup_defeats_hostile_insteadof_rewrite(bare_remote: Path, tmp_path: Path, monkeypatch):
    # A caller `url.<base>.insteadOf` whose prefix matches the bare repo_url
    # (e.g. the common `url."git@github.com:".insteadOf = https://github.com/`)
    # would reroute clone/pull/push off the credential-injected transport. The
    # identity pin in _git_env is a longer prefix match, so remote ops stay on
    # repo_url. Without the pin, this rewrite sends the clone to a dead decoy.
    hostile = tmp_path / "hostile_gitconfig"
    hostile.write_text('[url "file:///nonexistent-decoy/"]\n\tinsteadOf = file://\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))

    b = GitBackend(
        repo_url=bare_remote.as_uri(),
        github_token=TOKEN,
        local_path=tmp_path / "clone",
    )
    await b.setup()
    assert (b.path / "readme.md").exists()

    # A second setup() must revalidate cleanly: `remote get-url` would return the
    # rewritten decoy URL, but _validate_existing_clone reads the raw config value.
    await b.setup()
    assert "nonexistent-decoy" not in (b.path / ".git" / "config").read_text()
    raw_origin = _git(["config", "--get", "remote.origin.url"], b.path).stdout.strip()
    assert raw_origin == b.repo_url
