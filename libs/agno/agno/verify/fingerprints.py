"""State fingerprints: the no-op detector's sensor.

A fingerprint digests the world after an attempt. If two consecutive attempts digest the same,
the agent changed nothing between them. Not the same word as `env_fingerprint` in
agno.environments, which identifies what was run; this one measures what running did.
"""

import asyncio
import hashlib
import os
import subprocess
from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence, runtime_checkable

from agno.utils.log import log_warning

# Path components skipped on both the git path and the listing fallback. They are where
# verifiers (pytest, the interpreter) leave artefacts that would otherwise read as agent work.
DEFAULT_EXCLUDES: Sequence[str] = (".git", "__pycache__", ".pytest_cache", ".venv", "node_modules")


@runtime_checkable
class StateFingerprint(Protocol):
    """A stable digest of world state, cheap enough to run once per attempt. None means
    unknown; unknown never compares equal to anything, so it can never flag a no-op."""

    def capture(self) -> Optional[str]: ...

    async def acapture(self) -> Optional[str]: ...


class _HalfFingerprint:
    """Wraps an object that implements only `capture`, deriving `acapture`."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def capture(self) -> Optional[str]:
        return self.inner.capture()

    async def acapture(self) -> Optional[str]:
        if callable(getattr(self.inner, "acapture", None)):
            return await self.inner.acapture()
        return await asyncio.to_thread(self.inner.capture)


def coerce_fingerprint(obj: Any) -> StateFingerprint:
    """Accept a full StateFingerprint, or an object with only `capture`; reject the rest."""
    has_sync = callable(getattr(obj, "capture", None))
    has_async = callable(getattr(obj, "acapture", None))
    if has_sync and has_async:
        return obj
    if has_sync:
        return _HalfFingerprint(obj)
    raise ValueError(f"fingerprint must implement capture(); got {type(obj).__name__}")


def _normalise(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value or None


def safe_capture(fp: StateFingerprint) -> Optional[str]:
    """capture() with the failure rule applied: an exception, None or "" is unknown (None),
    logged, and never ends a run."""
    try:
        return _normalise(fp.capture())
    except Exception as exc:
        log_warning(f"Fingerprint capture failed; treating state as unknown: {type(exc).__name__}: {exc}")
        return None


async def asafe_capture(fp: StateFingerprint) -> Optional[str]:
    try:
        return _normalise(await fp.acapture())
    except Exception as exc:
        log_warning(f"Fingerprint capture failed; treating state as unknown: {type(exc).__name__}: {exc}")
        return None


def _excluded(rel_path: str, exclude: Sequence[str]) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    return any(part in exclude for part in parts if part)


class GitWorktreeFingerprint:
    """Digest of a git worktree: HEAD, status, staged and unstaged diffs, and the content of
    every untracked file.

    `path` only locates the repository; the digest always covers the whole worktree. The
    untracked-file content hashes are what make an edit to an untracked file visible: the
    status listing alone shows `?? notes.md` before and after. Ignored files are out of
    scope. Outside a repository the digest is the recursive (path, size, mtime_ns) listing
    under `path`. Paths with a component in `exclude` are skipped on both paths.
    """

    def __init__(self, path: str = ".", exclude: Sequence[str] = DEFAULT_EXCLUDES) -> None:
        self.path = path
        self.exclude = tuple(exclude)

    def _git(self, *args: str, cwd: str) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)

    def _toplevel(self) -> Optional[str]:
        """The repository root, or None when `path` is not inside a repository. Raises when
        git itself is unavailable or fails for another reason."""
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
            # `-uall` still lists a nested repository as a directory entry.
            digest.update(b"\x00dir")
        else:
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

        for args in (("diff", "--binary"), ("diff", "--binary", "--staged")):
            diff = self._git(*args, cwd=top)
            if diff.returncode != 0:
                raise RuntimeError(diff.stderr.decode("utf-8", errors="replace").strip() or "git diff failed")
            digest.update(diff.stdout)
            digest.update(b"\x00")

        for rel_path in sorted(untracked):
            self._hash_untracked(top, rel_path, digest)
        return digest.hexdigest()

    def _listing_digest(self) -> str:
        digest = hashlib.sha256()
        root = os.path.abspath(self.path)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in self.exclude)
            for filename in sorted(filenames):
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, root)
                if _excluded(rel, self.exclude):
                    continue
                try:
                    stat = os.lstat(full)
                except OSError:
                    continue
                digest.update(
                    f"{rel}\x00{stat.st_size}\x00{stat.st_mtime_ns}\n".encode("utf-8", errors="surrogateescape")
                )
        return digest.hexdigest()

    def capture(self) -> Optional[str]:
        top = self._toplevel()
        if top is None:
            return self._listing_digest()
        return self._git_digest(top)

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


def noop_between(previous: Optional[str], current: Optional[str]) -> bool:
    """The comparison rule: equal and both known."""
    return previous is not None and current is not None and previous == current


__all__ = [
    "DEFAULT_EXCLUDES",
    "CallableFingerprint",
    "GitWorktreeFingerprint",
    "StateFingerprint",
    "asafe_capture",
    "coerce_fingerprint",
    "noop_between",
    "safe_capture",
]
