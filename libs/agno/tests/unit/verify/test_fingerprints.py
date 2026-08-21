"""Unit tests for agno.verify.fingerprints (test 12 and the failure rule)."""

import asyncio
import os
import subprocess

import pytest

from agno.verify import CallableFingerprint, GitWorktreeFingerprint, StateFingerprint
from agno.verify.fingerprints import coerce_fingerprint, noop_between, safe_capture


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


def test_stable_when_nothing_changed(repo):
    fp = GitWorktreeFingerprint(str(repo))
    assert fp.capture() == fp.capture()


def test_differs_after_editing_tracked_file(repo):
    fp = GitWorktreeFingerprint(str(repo))
    before = fp.capture()
    (repo / "tracked.txt").write_text("v2\n")
    assert fp.capture() != before


def test_differs_after_editing_untracked_file_content(repo):
    fp = GitWorktreeFingerprint(str(repo))
    (repo / "notes.md").write_text("v1")
    created = fp.capture()
    (repo / "notes.md").write_text("v2")
    assert fp.capture() != created


def test_differs_after_second_file_in_untracked_directory(repo):
    fp = GitWorktreeFingerprint(str(repo))
    (repo / "newdir").mkdir()
    (repo / "newdir" / "a.py").write_text("a")
    one = fp.capture()
    (repo / "newdir" / "b.py").write_text("b")
    assert fp.capture() != one


def test_stable_when_excluded_artefact_appears(repo):
    fp = GitWorktreeFingerprint(str(repo))
    before = fp.capture()
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "lastfailed").write_text("{}")
    assert fp.capture() == before


def test_stable_with_untracked_nested_repository(repo):
    fp = GitWorktreeFingerprint(str(repo))
    (repo / "nested").mkdir()
    _git("init", "-q", cwd=repo / "nested")
    first = fp.capture()
    assert isinstance(first, str)
    assert fp.capture() == first


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


def test_non_repo_fallback_differs_on_edit_and_is_stable(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "f.txt").write_text("1")
    fp = GitWorktreeFingerprint(str(plain))
    first = fp.capture()
    assert fp.capture() == first
    (plain / "f.txt").write_text("22")
    assert fp.capture() != first


def test_missing_git_binary_returns_none(tmp_path, monkeypatch):
    fp = GitWorktreeFingerprint(str(tmp_path))

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert fp.capture() is None
    assert safe_capture(fp) is None


def test_head_and_staged_diff_are_digest_inputs(repo):
    fp = GitWorktreeFingerprint(str(repo))
    before = fp.capture()
    (repo / "tracked.txt").write_text("staged\n")
    _git("add", "tracked.txt", cwd=repo)
    staged = fp.capture()
    assert staged != before
    _git("commit", "-q", "-m", "advance head", cwd=repo)
    assert fp.capture() not in (before, staged)


def test_deleted_tracked_file_and_removed_untracked_file_change_digest(repo):
    fp = GitWorktreeFingerprint(str(repo))
    base = fp.capture()
    (repo / "scratch.txt").write_text("x")
    with_untracked = fp.capture()
    (repo / "scratch.txt").unlink()
    assert fp.capture() == base
    (repo / "tracked.txt").unlink()
    assert fp.capture() not in (base, with_untracked)


def test_path_with_space_is_hashed(repo):
    fp = GitWorktreeFingerprint(str(repo))
    (repo / "my notes.md").write_text("a")
    first = fp.capture()
    (repo / "my notes.md").write_text("b")
    assert fp.capture() != first


@pytest.mark.asyncio
async def test_acapture_matches_capture(repo):
    fp = GitWorktreeFingerprint(str(repo))
    assert await fp.acapture() == fp.capture()


def test_callable_fingerprint_sync_and_async():
    fp = CallableFingerprint(lambda: "abc")
    assert fp.capture() == "abc"
    assert asyncio.run(fp.acapture()) == "abc"

    async def afn():
        return "from-afn"

    assert asyncio.run(CallableFingerprint(lambda: "sync", afn=afn).acapture()) == "from-afn"


def test_failure_rule_exception_none_and_empty_are_unknown():
    def boom():
        raise OSError("disk")

    assert safe_capture(CallableFingerprint(boom)) is None
    assert safe_capture(CallableFingerprint(lambda: None)) is None
    assert safe_capture(CallableFingerprint(lambda: "")) is None


def test_unknown_never_equals():
    assert noop_between(None, None) is False
    assert noop_between("a", None) is False
    assert noop_between("a", "a") is True
    assert noop_between("a", "b") is False


def test_capture_only_object_gets_acapture():
    class CaptureOnly:
        def capture(self):
            return "c"

    fp = coerce_fingerprint(CaptureOnly())
    assert isinstance(fp, StateFingerprint)
    assert asyncio.run(fp.acapture()) == "c"


def test_object_without_capture_is_rejected():
    with pytest.raises(ValueError):
        coerce_fingerprint(object())


def test_symlink_target_is_part_of_digest(repo):
    if os.name == "nt":
        pytest.skip("symlinks need privileges on Windows")
    fp = GitWorktreeFingerprint(str(repo))
    os.symlink("tracked.txt", repo / "link")
    first = fp.capture()
    os.unlink(repo / "link")
    os.symlink("missing.txt", repo / "link")
    assert fp.capture() != first


def test_chmod_on_untracked_file_changes_digest(repo):
    fp = GitWorktreeFingerprint(str(repo))
    script = repo / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    os.chmod(script, 0o644)
    before = fp.capture()
    os.chmod(script, 0o755)
    assert fp.capture() != before
    os.chmod(script, 0o644)
    assert fp.capture() == before


def test_chmod_changes_listing_fallback_digest(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    script = plain / "run.sh"
    script.write_text("#!/bin/sh\n")
    os.chmod(script, 0o644)
    fp = GitWorktreeFingerprint(str(plain))
    before = fp.capture()
    os.chmod(script, 0o755)
    assert fp.capture() != before
