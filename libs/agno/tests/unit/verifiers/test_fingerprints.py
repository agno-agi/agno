"""Unit tests for agno.verifiers.fingerprints: the digest and the failure rule."""

import os
import subprocess
import sys

import pytest

from agno.verifiers.fingerprints import (
    CallableFingerprint,
    GitWorktreeFingerprint,
    StateFingerprint,
    asafe_capture,
    coerce_fingerprint,
    require_sync_fingerprint,
    safe_capture,
    state_unchanged,
)


def _git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "-q", cwd=root)
    (root / "tracked.txt").write_text("v1\n")
    _git("add", "tracked.txt", cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)
    return root


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _nested_repo(repo):
    (repo / "vendor").mkdir()
    _git("init", "-q", cwd=repo / "vendor")
    _write(repo / "vendor" / "lib.py", "x = 1")


def _symlink(repo, target):
    if (repo / "link").is_symlink():
        os.unlink(repo / "link")
    os.symlink(target, repo / "link")


def _chmod_script(repo, mode):
    script = repo / "run.sh"
    if not script.exists():
        script.write_text("#!/bin/sh\necho hi\n")
    os.chmod(script, mode)


@pytest.mark.parametrize(
    "setup, mutate",
    [
        (lambda repo: None, lambda repo: _write(repo / "tracked.txt", "v2\n")),
        (lambda repo: _write(repo / "notes.md", "v1"), lambda repo: _write(repo / "notes.md", "v2")),
        (lambda repo: _write(repo / "my notes.md", "a"), lambda repo: _write(repo / "my notes.md", "b")),
        (
            lambda repo: _write(repo / "tracked.txt", "staged\n"),
            lambda repo: _git("add", "tracked.txt", cwd=repo),
        ),
        (
            lambda repo: (_write(repo / "tracked.txt", "head\n"), _git("add", "tracked.txt", cwd=repo)),
            lambda repo: _git("commit", "-q", "-m", "advance head", cwd=repo),
        ),
        (lambda repo: None, lambda repo: (repo / "tracked.txt").unlink()),
        pytest.param(
            lambda repo: _symlink(repo, "tracked.txt"),
            lambda repo: _symlink(repo, "missing.txt"),
            marks=pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows"),
        ),
        (lambda repo: _chmod_script(repo, 0o644), lambda repo: _chmod_script(repo, 0o755)),
        # `git status -uall` lists a nested repository as one directory entry, so a constant
        # digest for it would make an agent working inside a vendored checkout read as idle.
        (_nested_repo, lambda repo: _write(repo / "vendor" / "lib.py", "x = 2  # real work")),
    ],
    ids=[
        "tracked-edit",
        "untracked-content",
        "path-with-space",
        "staged",
        "commit",
        "delete-tracked",
        "symlink-retarget",
        "chmod-untracked",
        "nested-repo-edit",
    ],
)
def test_worktree_edit_changes_the_digest(repo, setup, mutate):
    fp = GitWorktreeFingerprint(str(repo))
    setup(repo)
    before = fp.capture()
    assert fp.capture() == before
    mutate(repo)
    assert fp.capture() != before


def _pycache(repo):
    _write(repo / "__pycache__" / "x.pyc", "\x00")
    _write(repo / ".pytest_cache" / "lastfailed", "{}")


def _tracked_vendor(repo):
    _write(repo / "node_modules" / "pkg.js", "v1")
    _git("add", "-f", "-A", cwd=repo)
    _git("commit", "-q", "-m", "vendor", cwd=repo)


@pytest.mark.parametrize(
    "setup, mutate",
    [
        (lambda repo: None, _pycache),
        # `exclude` applies to the two tracked diffs as well as the status listing.
        (_tracked_vendor, lambda repo: _write(repo / "node_modules" / "pkg.js", "v2 changed")),
    ],
    ids=["untracked-pycache", "tracked-node-modules-edit"],
)
def test_stable_when_excluded_artefact_appears(repo, setup, mutate):
    setup(repo)
    fp = GitWorktreeFingerprint(str(repo))
    before = fp.capture()
    mutate(repo)
    assert fp.capture() == before


def test_subdirectory_path_digests_whole_worktree(repo):
    (repo / "sub").mkdir()
    (repo / "sub" / "inner.txt").write_text("x")
    _git("add", "sub/inner.txt", cwd=repo)
    _git("commit", "-q", "-m", "sub", cwd=repo)
    assert GitWorktreeFingerprint(str(repo / "sub")).capture() == GitWorktreeFingerprint(str(repo)).capture()
    # An edit outside the subdirectory is still visible from inside it.
    before = GitWorktreeFingerprint(str(repo / "sub")).capture()
    (repo / "tracked.txt").write_text("changed\n")
    assert GitWorktreeFingerprint(str(repo / "sub")).capture() != before


def test_unborn_head_repo_is_stable_string(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    _git("init", "-q", cwd=root)
    (root / "a.txt").write_text("a")
    fp = GitWorktreeFingerprint(str(root))
    first = fp.capture()
    assert isinstance(first, str) and first
    assert fp.capture() == first
    (root / "a.txt").write_text("b")
    assert fp.capture() != first


def _equal_length_edit(target):
    # The listing fallback never hashes content, so size and mtime are what stand between an
    # `a - b` -> `a + b` fix and a false unchanged state.
    target.write_text("def add(a, b):\n    return a + b\n")
    os.utime(target, ns=(0, os.stat(target).st_mtime_ns + 1_000_000))


@pytest.mark.parametrize(
    "mutate",
    [_equal_length_edit, lambda target: os.chmod(target, 0o755)],
    ids=["equal-length-edit", "chmod"],
)
def test_equal_length_edit_outside_a_repo_is_visible(tmp_path, mutate):
    work = tmp_path / "plain"
    work.mkdir()
    target = work / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n")
    os.chmod(target, 0o644)
    fp = GitWorktreeFingerprint(str(work))  # not a repo -> listing fallback
    before = fp.capture()
    assert fp.capture() == before
    mutate(target)
    assert fp.capture() != before


def test_unlistable_directory_is_unknown_not_a_partial_digest(tmp_path):
    """os.walk skips a subtree it cannot list and says nothing. A digest over only the readable
    part is stable, so work inside the unreadable part would read as an unchanged state and end the run."""
    work = tmp_path / "work"
    (work / "secret").mkdir(parents=True)
    (work / "visible.txt").write_text("v")
    (work / "secret" / "out.txt").write_text("before")
    os.chmod(work / "secret", 0o111)  # traversable by path, not listable
    try:
        fp = GitWorktreeFingerprint(str(work))  # not a repo -> listing fallback
        assert fp.capture() is None
    finally:
        os.chmod(work / "secret", 0o700)


async def test_callable_fingerprint_sync_and_async():
    fp = CallableFingerprint(lambda: "abc")
    assert fp.capture() == "abc"
    assert await fp.acapture() == "abc"

    async def afn():
        return "from-afn"

    assert await CallableFingerprint(lambda: "sync", afn=afn).acapture() == "from-afn"


def test_failure_rule_exception_none_and_empty_are_unknown():
    def boom():
        raise OSError("disk")

    assert safe_capture(CallableFingerprint(boom)) is None
    assert safe_capture(CallableFingerprint(lambda: None)) is None
    assert safe_capture(CallableFingerprint(lambda: "")) is None
    # Unknown never equals, not even another unknown.
    assert state_unchanged(None, None) is False
    assert state_unchanged("a", None) is False
    assert state_unchanged("a", "a") is True
    assert state_unchanged("a", "b") is False


class CaptureOnly:
    def capture(self):
        return "c"


class AcaptureOnly:
    async def acapture(self):
        return "a"


@pytest.mark.parametrize("entry", [CaptureOnly, AcaptureOnly, object], ids=["capture-only", "acapture-only", "neither"])
async def test_acapture_only_fingerprint_is_refused_by_run(entry):
    if entry is object:
        with pytest.raises(ValueError):
            coerce_fingerprint(object())
        return
    fp = coerce_fingerprint(entry())
    assert isinstance(fp, StateFingerprint)
    if entry is CaptureOnly:
        require_sync_fingerprint(fp)
        assert safe_capture(fp) == "c"
        assert await asafe_capture(fp) == "c"
    else:
        with pytest.raises(ValueError, match=r"Cannot use AcaptureOnly \(an async fingerprint\) with `run\(\)`"):
            require_sync_fingerprint(fp)
        assert await asafe_capture(fp) == "a"


# ---------------------------------------------------------------------------
# Repository-configured programs, submodules and git environment
# ---------------------------------------------------------------------------


def _recording_hook(tmp_path):
    """A shell program that records each run in a marker file."""
    marker = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\necho ran >> {marker}\necho '/'\n")
    hook.chmod(0o755)
    return hook, marker


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell hook")
def test_fingerprint_never_runs_repository_configured_programs(repo, tmp_path):
    hook, marker = _recording_hook(tmp_path)
    (repo / "tracked.txt").write_text("b\n")
    _git("config", "core.fsmonitor", str(hook), cwd=repo)
    _git("config", "diff.external", str(hook), cwd=repo)
    fingerprint = GitWorktreeFingerprint(str(repo))
    digest = fingerprint.capture()
    assert digest is not None
    assert not marker.exists()
    (repo / "tracked.txt").write_text("c\n")
    assert fingerprint.capture() != digest


@pytest.mark.skipif(sys.platform == "win32", reason="posix paths")
def test_fingerprint_sees_edits_inside_a_submodule(repo, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    _git("init", "-q", cwd=sub)
    (sub / "s.txt").write_text("s\n")
    _git("add", ".", cwd=sub)
    _git("commit", "-q", "-m", "sub", cwd=sub)
    _git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "sub", cwd=repo)
    _git("commit", "-q", "-m", "add sub", cwd=repo)
    fingerprint = GitWorktreeFingerprint(str(repo))
    clean = fingerprint.capture()
    (repo / "sub" / "s.txt").write_text("edit A\n")
    edit_a = fingerprint.capture()
    (repo / "sub" / "s.txt").write_text("edit B\n")
    edit_b = fingerprint.capture()
    assert clean != edit_a
    assert edit_a != edit_b


def test_fingerprint_drops_git_config_from_the_environment(repo, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    _git("init", "-q", cwd=other)
    fp = GitWorktreeFingerprint(str(repo))
    clean = fp.capture()
    # An inherited GIT_DIR / GIT_WORK_TREE cannot redirect the digest to another repository.
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert fp.capture() == clean
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")

    # Inherited GIT_CONFIG_* and GIT_EXTERNAL_DIFF cannot inject a program to run.
    hook, marker = _recording_hook(tmp_path)
    (repo / "tracked.txt").write_text("b\n")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hook))
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", str(hook))
    assert fp.capture() is not None
    assert not marker.exists()
