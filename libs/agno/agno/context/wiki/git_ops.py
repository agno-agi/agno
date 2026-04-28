"""
Git CLI wrapper for the WikiContextProvider GitBackend.
=======================================================

Async subprocess wrapper around the system ``git`` binary. No
``gitpython`` / ``pygit2`` dependency — the wiki workflow only needs a
handful of porcelain commands (``clone``, ``pull --rebase``, ``add``,
``commit``, ``push``, ``status``, ``rev-parse``, ``config``,
``remote``).

Two invariants this module enforces:

- ``GIT_TERMINAL_PROMPT=0`` is always set. A bad PAT must fail fast
  rather than block on stdin asking the operator to type a password.
- Subprocess stderr is scrubbed before any exception or log line. The
  authenticated remote URL embeds the PAT as
  ``https://x-access-token:<TOKEN>@github.com/...``; if git echoes that
  back in an error, we strip the token before it reaches a logger.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git subprocess exits non-zero.

    The ``stderr`` attribute is already scrubbed of any registered
    secrets — never re-add the unscrubbed source.
    """

    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        # Don't shadow ``BaseException.args`` (typed as ``tuple[Any, ...]``)
        # by reassigning it to a list — store under ``cmd`` instead.
        self.cmd: list[str] = list(args)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git {' '.join(args)} exited {returncode}: {stderr}")


@dataclass
class GitResult:
    """Result of a ``git`` invocation."""

    returncode: int
    stdout: str
    stderr: str


@dataclass
class Scrubber:
    """Replaces registered secrets with ``***`` in arbitrary text.

    Built once at GitBackend construction with the PAT and the full
    authenticated URL, then passed into every ``run()`` call. Keeping
    the scrubber as data (not a closure) makes it easy to unit-test in
    isolation and to share between sync log lines and async stderr.
    """

    secrets: list[str] = field(default_factory=list)

    def add(self, secret: str | None) -> None:
        if secret and secret not in self.secrets:
            self.secrets.append(secret)

    def scrub(self, text: str) -> str:
        if not text:
            return text
        out = text
        for secret in self.secrets:
            if secret:
                out = out.replace(secret, "***")
        # Belt-and-braces: catch any ``x-access-token:<anything>@`` form
        # that slipped through (e.g. a stderr that includes a slightly
        # different URL encoding than what we registered).
        out = _XACCESS_RE.sub("x-access-token:***@", out)
        return out


# Matches ``x-access-token:<token>@`` regardless of the token value.
_XACCESS_RE = re.compile(r"x-access-token:[^@\s]+@")


async def run(
    args: list[str],
    *,
    cwd: Path | str,
    scrubber: Scrubber | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    timeout: float | None = 120.0,
) -> GitResult:
    """Run ``git <args>`` asynchronously and capture stdout/stderr.

    :param args: Arguments to ``git`` (without the leading ``git``).
    :param cwd: Working directory. Required — git is path-sensitive and
        a missing cwd is almost always a bug.
    :param scrubber: Optional ``Scrubber`` applied to stdout/stderr
        before they reach the caller (or ``GitError``).
    :param check: If True (default), non-zero exit raises ``GitError``.
    :param env: Extra environment variables. ``GIT_TERMINAL_PROMPT=0``
        is always added so a bad PAT fails fast instead of hanging on
        stdin.
    :param timeout: Wall-clock seconds before the subprocess is killed.
        ``None`` disables the timeout.
    :return: ``GitResult(returncode, stdout, stderr)`` with both streams
        already scrubbed.
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    full_env["GIT_TERMINAL_PROMPT"] = "0"

    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=full_env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        safe_args = [scrubber.scrub(a) for a in args] if scrubber is not None else list(args)
        raise GitError(
            safe_args,
            -1,
            f"git {' '.join(safe_args)} timed out after {timeout}s",
        ) from None

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    if scrubber is not None:
        stdout = scrubber.scrub(stdout)
        stderr = scrubber.scrub(stderr)

    result = GitResult(returncode=proc.returncode or 0, stdout=stdout, stderr=stderr)
    if check and result.returncode != 0:
        # Scrub args too — `git clone <authenticated-url> ...` would
        # otherwise leak the PAT into the error string we raise.
        safe_args = [scrubber.scrub(a) for a in args] if scrubber is not None else list(args)
        raise GitError(safe_args, result.returncode, result.stderr.strip())
    return result


def build_authenticated_url(repo_url: str, token: str) -> str:
    """Build an HTTPS URL with a PAT embedded for ``x-access-token`` auth.

    Accepts either an ``https://github.com/owner/repo[.git]`` URL or one
    that already has a ``x-access-token:...@`` prefix. SSH URLs
    (``git@github.com:owner/repo.git``) are rejected — PAT auth only
    works with HTTPS.
    """
    if not token:
        raise ValueError("PAT is required to build an authenticated URL")
    if repo_url.startswith("git@"):
        raise ValueError(
            "GitBackend requires an HTTPS clone URL when using a PAT; got SSH URL. "
            "Use the https://github.com/<owner>/<repo>.git form."
        )
    if "://" not in repo_url:
        raise ValueError(f"unrecognised repo URL: {repo_url!r}")
    scheme, rest = repo_url.split("://", 1)
    if scheme.lower() != "https":
        raise ValueError(f"GitBackend requires https://; got {scheme!r}")
    # Strip any pre-existing user-info segment (so re-running setup with
    # a rotated PAT doesn't double-stack credentials).
    if "@" in rest.split("/", 1)[0]:
        rest = rest.split("@", 1)[1]
    return f"https://x-access-token:{token}@{rest}"
