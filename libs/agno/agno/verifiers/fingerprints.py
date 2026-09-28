"""State fingerprints: the unchanged-state detector's sensor.

A fingerprint digests the world after an attempt. If two consecutive attempts digest the same,
the agent changed nothing between them. Not the same word as `env_fingerprint` in
agno.environments, which identifies what was run; this one measures what running did.
"""

import asyncio
import hashlib
import inspect
import os
import subprocess
from typing import Any, Awaitable, Callable, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from agno.utils.log import log_warning

# Path components skipped on both the git path and the listing fallback. They are where
# verifiers (pytest, the interpreter) leave artifacts that would otherwise read as agent work.
DEFAULT_EXCLUDES: Sequence[str] = (".git", "__pycache__", ".pytest_cache", ".venv", "node_modules")

# A git command that has not returned by then is hung on something outside the worktree.
_GIT_TIMEOUT_SECONDS = 60.0

# Repository config that makes `git status` or `git diff` run a program: the fsmonitor, an
# external diff, and the post-index-change hook `git status` fires when it refreshes the
# index. The repository's own config is inside the tree the agent writes, so each is pinned
# off on the command line. A clean filter the repository configures still runs: git applies
# it whenever it re-reads a modified tracked file, and there is no switch to turn filters off.
_GIT_CONFIG_OVERRIDES = ("core.fsmonitor=false", "diff.external=", "core.hooksPath=/dev/null")


@runtime_checkable
class StateFingerprint(Protocol):
    """A stable digest of world state, cheap enough to run once per attempt, from a ``capture``
    method, an ``acapture`` method, or both. ``run()`` calls ``capture``; ``arun()`` awaits
    ``acapture``, or runs ``capture`` on a worker thread. None means unknown; unknown never
    compares equal to anything, so it can never flag an unchanged state.
    """


def coerce_fingerprint(obj: Any) -> StateFingerprint:
    """Accept an object with `capture`, `acapture`, or both; reject the rest."""
    if callable(getattr(obj, "capture", None)) or callable(getattr(obj, "acapture", None)):
        return obj
    raise ValueError(f"Fingerprint must implement capture() or acapture(), got {type(obj).__name__}")


def require_sync_fingerprint(fp: Any) -> None:
    """Raise when `run()` cannot capture this fingerprint."""
    capture = getattr(fp, "capture", None)
    if not callable(capture) or inspect.iscoroutinefunction(capture):
        raise ValueError(f"Cannot use {type(fp).__name__} (an async fingerprint) with `run()`. Use `arun()` instead.")


def _normalize(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value or None


def safe_capture(fp: Any) -> Optional[str]:
    """capture() with the failure rule applied: an exception, None or "" is unknown (None) and
    never ends a run; the attempt records the unknown state.
    """
    try:
        return _normalize(fp.capture())
    except Exception as exc:
        log_warning(f"Could not capture fingerprint: {exc}")
        return None


async def asafe_capture(fp: Any) -> Optional[str]:
    try:
        if callable(getattr(fp, "acapture", None)):
            value = await fp.acapture()
        else:
            value = await asyncio.to_thread(fp.capture)
        return _normalize(value)
    except Exception as exc:
        log_warning(f"Could not capture fingerprint: {exc}")
        return None


def _excluded(rel_path: str, exclude: Sequence[str]) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    return any(part in exclude for part in parts if part)


def _walk_stats(root: str, exclude: Sequence[str]) -> List[Tuple[str, os.stat_result]]:
    """Every non-excluded file under `root` as (relative path, lstat), sorted.

    Traversal errors are raised, never swallowed. `os.walk` reports them to `onerror` and
    otherwise skips that subtree silently, which would produce a stable digest over only the
    readable part of the tree: work done inside an unlistable directory would then read as an
    unchanged state and end the run early, with nothing to say it had gone blind.
    """

    def blow_up(error: OSError) -> None:
        raise error

    found: List[Tuple[str, os.stat_result]] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=blow_up):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, root)
            if _excluded(rel, exclude):
                continue
            try:
                found.append((rel, os.lstat(full)))
            except FileNotFoundError:
                # A file vanishing mid-walk is normal while an agent works; skip it. Any other
                # OSError propagates, for the same reason traversal errors do.
                continue
    return found


class GitWorktreeFingerprint:
    """Digest of a git worktree: HEAD, status, staged and unstaged diffs, and the content of
    every untracked file.

    `path` only locates the repository; the digest always covers the whole worktree. The
    untracked-file content hashes are what make an edit to an untracked file visible: the
    status listing alone shows `?? notes.md` before and after. Ignored files are out of
    scope. Outside a repository the digest is the recursive (path, size, mtime_ns) listing
    under `path`. Paths with a component in `exclude` are skipped on both paths.
    """

    def __init__(
        self, path: str = ".", exclude: Sequence[str] = DEFAULT_EXCLUDES, extra_excludes: Sequence[str] = ()
    ) -> None:
        # `exclude` replaces the defaults, `extra_excludes` adds to them.
        self.exclude = tuple(exclude) + tuple(extra_excludes)
        self.path = path

    def _git(self, *args: str, cwd: str) -> "subprocess.CompletedProcess[bytes]":
        # LC_ALL=C keeps git's messages English for the not-a-repository check; inherited
        # GIT_* variables and config overrides are dropped so the environment cannot redirect git.
        env = {**os.environ, "LC_ALL": "C", "LC_MESSAGES": "C"}
        for leaked in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_EXTERNAL_DIFF"):
            env.pop(leaked, None)
        for leaked in [key for key in env if key.startswith("GIT_CONFIG")]:
            env.pop(leaked, None)
        overrides = [arg for key in _GIT_CONFIG_OVERRIDES for arg in ("-c", key)]
        return subprocess.run(
            ["git", *overrides, *args],
            cwd=cwd,
            capture_output=True,
            check=False,
            env=env,
            timeout=_GIT_TIMEOUT_SECONDS,
        )

    def _exclude_pathspec(self) -> List[str]:
        """Pathspecs that keep the two diffs to the same scope as the status listing."""
        specs: List[str] = []
        for name in self.exclude:
            specs.append(f":(exclude,glob){name}/**")
            specs.append(f":(exclude,glob)**/{name}/**")
        return specs

    def _toplevel(self) -> Optional[str]:
        """The repository root, or None when `path` is not inside a repository. Raises when
        git itself is unavailable or fails for another reason.
        """
        result = self._git("rev-parse", "--show-toplevel", cwd=self.path)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace").strip()
        if result.returncode == 128 and b"not a git repository" in result.stderr.lower():
            return None
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "git rev-parse failed")

    def _hash_untracked(self, top: str, rel_path: str, digest: "hashlib._Hash") -> None:
        full = os.path.join(top, rel_path)
        digest.update(rel_path.encode("utf-8", errors="surrogateescape"))
        if os.path.islink(full):
            digest.update(b"\x00link:" + os.readlink(full).encode("utf-8", errors="surrogateescape"))
        elif os.path.isdir(full):
            # `-uall` still lists a nested repository as a single directory entry, so digesting
            # a constant here would make every edit inside it invisible — an agent working in a
            # cloned dependency would read as completely idle. Walk it instead.
            digest.update(b"\x00dir")
            for sub_rel, stat in _walk_stats(full, self.exclude):
                digest.update(
                    f"\x00{sub_rel}\x00{stat.st_size}\x00{stat.st_mtime_ns}\x00"
                    f"{'x' if stat.st_mode & 0o111 else '-'}".encode("utf-8", errors="surrogateescape")
                )
        else:
            # The executable bit is world state an agent changes on purpose (chmod +x on a
            # script); mirror what git records for tracked files (100644 vs 100755).
            try:
                executable = bool(os.lstat(full).st_mode & 0o111)
            except OSError:
                executable = False
            digest.update(b"\x00x" if executable else b"\x00-")
            with open(full, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 16), b""):
                    digest.update(chunk)
        digest.update(b"\x00")

    def _git_digest(self, top: str) -> str:
        digest = hashlib.sha256()
        head = self._git("rev-parse", "--verify", "-q", "HEAD", cwd=top)
        digest.update(head.stdout.strip() if head.returncode == 0 else b"unborn")
        digest.update(b"\x00")

        status = self._git("status", "--porcelain=v1", "-z", "-uall", "--no-renames", cwd=top)
        if status.returncode != 0:
            raise RuntimeError(status.stderr.decode("utf-8", errors="replace").strip() or "git status failed")
        untracked = []
        submodules = []
        for entry in status.stdout.split(b"\x00"):
            if len(entry) < 4:
                continue
            code = entry[:2]
            rel_path = entry[3:].decode("utf-8", errors="surrogateescape")
            if _excluded(rel_path, self.exclude):
                continue
            digest.update(entry)
            digest.update(b"\x00")
            if code == b"??":
                untracked.append(rel_path)
            elif os.path.isdir(os.path.join(top, rel_path)):
                # A registered submodule shows up as one "M sub" line whatever changed inside
                # it; its tree is walked so two different edits do not digest the same.
                submodules.append(rel_path)

        pathspec = self._exclude_pathspec()
        for args in (("diff", "--binary"), ("diff", "--binary", "--staged")):
            diff = self._git(*args, "--no-ext-diff", "--no-textconv", "--no-color", "--", ".", *pathspec, cwd=top)
            if diff.returncode != 0:
                raise RuntimeError(diff.stderr.decode("utf-8", errors="replace").strip() or "git diff failed")
            digest.update(diff.stdout)
            digest.update(b"\x00")

        for rel_path in sorted(untracked):
            self._hash_untracked(top, rel_path, digest)
        for rel_path in sorted(submodules):
            self._hash_untracked(top, rel_path, digest)
        return digest.hexdigest()

    def _listing_digest(self) -> str:
        digest = hashlib.sha256()
        root = os.path.abspath(self.path)
        for rel, stat in _walk_stats(root, self.exclude):
            executable = "x" if stat.st_mode & 0o111 else "-"
            digest.update(
                f"{rel}\x00{stat.st_size}\x00{stat.st_mtime_ns}\x00{executable}\n".encode(
                    "utf-8", errors="surrogateescape"
                )
            )
        return digest.hexdigest()

    def capture(self) -> Optional[str]:
        """The digest, or None when git is unavailable or any step fails (unknown state)."""
        try:
            top = self._toplevel()
            if top is None:
                return self._listing_digest()
            return self._git_digest(top)
        except Exception as exc:
            log_warning(f"Could not capture fingerprint for {self.path}: {exc}")
            return None

    async def acapture(self) -> Optional[str]:
        return await asyncio.to_thread(self.capture)


class CallableFingerprint:
    """Wrap any `() -> Optional[str]`; `afn` is awaited on the async path when given."""

    def __init__(
        self,
        fn: Callable[[], Optional[str]],
        afn: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    ) -> None:
        self.fn = fn
        self.afn = afn

    def capture(self) -> Optional[str]:
        return self.fn()

    async def acapture(self) -> Optional[str]:
        if self.afn is not None:
            return await self.afn()
        return await asyncio.to_thread(self.fn)


def state_unchanged(previous: Optional[str], current: Optional[str]) -> bool:
    """The comparison rule: equal and both known."""
    return previous is not None and current is not None and previous == current
