"""
WikiBackend — pluggable I/O layer behind WikiContextProvider.
=============================================================

The provider owns the agent-facing contract (two tools, two sub-agents).
The backend owns the on-disk wiki directory and any synchronisation
with an external store. Two concrete backends ship today:

- ``FileSystemBackend`` — the directory is the source of truth. ``sync``
  and ``commit_after_write`` are no-ops. Demoable with no auth, no
  network. The path that proves the design works.
- ``GitBackend`` — the directory is a clone of a remote git repo. ``sync``
  pulls; ``commit_after_write`` stages, commits, rebases on top of the
  remote, and pushes. PAT auth via ``github_token``.

Both expose the same surface so the provider doesn't branch on backend
type, and a third backend (S3, Notion, GitHub App auth, etc.) can drop
in without touching ``WikiContextProvider``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agno.context.provider import Status
from agno.context.wiki.git_ops import GitError, Scrubber, build_authenticated_url
from agno.context.wiki.git_ops import run as git_run
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    pass


class WikiBackendError(RuntimeError):
    """Raised when a backend cannot complete its setup or sync.

    Distinct from ``GitError`` because some failures (e.g. existing
    clone with a different remote) aren't subprocess errors — they're
    safety guards the provider's caller needs to react to (usually by
    setting ``force_clone=True`` after confirming nothing important is
    in the local clone).
    """


@dataclass
class CommitSummary:
    """What a write hook actually committed."""

    sha: str
    message: str
    files_changed: int


class WikiBackend(ABC):
    """Pluggable I/O layer backing a ``WikiContextProvider``.

    Subclasses own the on-disk path the sub-agents read and write
    against. ``setup`` runs once before the provider serves any
    request; ``sync`` runs before each read; ``commit_after_write``
    runs after each write.
    """

    def __init__(self, *, path: Path) -> None:
        self.path: Path = Path(path).expanduser().resolve()

    @abstractmethod
    async def setup(self) -> None:
        """Make ``self.path`` ready to serve. Idempotent.

        For a filesystem backend this is ``mkdir -p``. For a git backend
        it's clone-or-validate-existing-clone. Either way, after
        ``setup`` returns, the provider can list/read/write under
        ``self.path``.
        """

    @abstractmethod
    async def sync(self) -> None:
        """Bring local content up-to-date with the source of truth.

        FS: no-op. Git: ``pull --rebase`` so a stale local clone
        doesn't serve stale content to a read sub-agent.
        """

    @abstractmethod
    async def commit_after_write(self, *, model=None) -> CommitSummary | None:  # noqa: ANN001
        """Persist any changes the write sub-agent made. Return ``None`` if nothing changed.

        FS: no-op (returns ``None``). Git: ``add -A``, summarise the
        diff into a one-line message, commit, rebase onto remote,
        push. The summary is logged by the provider so the caller has
        an audit trail without parsing transcripts.

        ``model`` is forwarded by the provider so backends that need
        to summarise a diff can reuse the same model the sub-agents
        run on.
        """

    def status(self) -> Status:
        """Synchronous health check. Must not block on network."""
        return Status(ok=self.path.exists() and self.path.is_dir(), detail=str(self.path))

    async def astatus(self) -> Status:
        """Async health check. Default mirrors ``status``."""
        return self.status()

    # -----------------------------------------------------------------
    # Helper for write sub-agents
    # -----------------------------------------------------------------

    async def summarize_diff(
        self,
        *,
        diff: str,
        model,  # noqa: ANN001 — late import to avoid cycle
    ) -> str:
        """Summarise a staged diff into an imperative one-liner under 72 chars.

        Used by ``GitBackend.commit_after_write`` (and any future backend
        that needs a commit message). Lives on the ABC so subclasses can
        share the prompt without duplicating it. Falls back to a generic
        message if the model is unavailable or returns something
        unusable.
        """
        from datetime import datetime, timezone

        fallback = f"Update wiki ({datetime.now(timezone.utc).isoformat(timespec='seconds')})"
        if model is None or not diff.strip():
            return fallback
        try:
            from agno.agent import Agent

            summarizer = Agent(
                id="wiki-commit-summarizer",
                name="Wiki Commit Summarizer",
                model=model,
                instructions=_COMMIT_SUMMARY_INSTRUCTIONS,
                markdown=False,
            )
            output = await summarizer.arun(_truncate_diff(diff))
            text = (
                output.get_content_as_string()
                if hasattr(output, "get_content_as_string")
                else str(output.content) or ""
            ).strip()
        except Exception as exc:
            log_warning(f"wiki commit summarizer failed: {type(exc).__name__}: {exc}")
            return fallback
        # Strip surrounding quotes/backticks/leading list markers; clamp
        # length. The prompt asks for one line under 72 chars, but models
        # sometimes wrap.
        first_line = text.splitlines()[0] if text else ""
        first_line = first_line.strip().strip("`'\"")
        first_line = re.sub(r"^[-*+]\s+", "", first_line)
        if not first_line:
            return fallback
        if len(first_line) > 72:
            first_line = first_line[:71].rstrip() + "…"
        return first_line


class FileSystemBackend(WikiBackend):
    """Wiki backend that's just a local directory. No remote, no auth."""

    def __init__(self, path: Path | str) -> None:
        super().__init__(path=Path(path))

    async def setup(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        log_debug(f"FileSystemBackend ready at {self.path}")

    async def sync(self) -> None:
        return None

    async def commit_after_write(self, *, model=None) -> CommitSummary | None:  # noqa: ANN001
        return None

    def status(self) -> Status:
        if not self.path.exists():
            return Status(ok=False, detail=f"path does not exist: {self.path}")
        if not self.path.is_dir():
            return Status(ok=False, detail=f"path is not a directory: {self.path}")
        return Status(ok=True, detail=str(self.path))


class GitBackend(WikiBackend):
    """Wiki backend backed by a git remote.

    On ``setup`` the backend either clones ``repo_url@branch`` into
    ``local_path`` or validates that an existing clone matches. On
    ``commit_after_write`` it stages, commits with an LLM-summarised
    one-liner, rebases onto the remote, and pushes.

    PAT auth is the only auth supported today: pass ``github_token`` (or
    let the caller pull it from the environment). The token is
    embedded in ``self._authenticated_url`` once at construction; never
    log it directly. The backend's ``Scrubber`` is wired into every
    ``git_ops.run`` call so token leakage from git's own stderr is
    blocked at the source.
    """

    def __init__(
        self,
        *,
        repo_url: str,
        branch: str = "main",
        github_token: str,
        local_path: Path | str | None = None,
        force_clone: bool = False,
        author_name: str = "Agno Wiki Bot",
        author_email: str = "wiki-bot@agno.local",
    ) -> None:
        if not github_token:
            raise ValueError("GitBackend: github_token is required")
        if not repo_url:
            raise ValueError("GitBackend: repo_url is required")
        self.repo_url: str = repo_url
        self.branch: str = branch
        self.github_token: str = github_token
        self.force_clone: bool = force_clone
        self.author_name: str = author_name
        self.author_email: str = author_email

        self._authenticated_url: str = build_authenticated_url(repo_url, github_token)
        self._scrubber: Scrubber = Scrubber()
        self._scrubber.add(github_token)
        self._scrubber.add(self._authenticated_url)

        resolved = Path(local_path).expanduser().resolve() if local_path else _default_clone_path(repo_url)
        super().__init__(path=resolved)

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def setup(self) -> None:
        # Three states for `self.path`:
        #   1. Valid existing clone of repo_url@branch -> reuse.
        #   2. Existing clone with mismatched remote/branch -> raise,
        #      or wipe + reclone if force_clone=True.
        #   3. Missing or non-clone -> reclone (wiping non-empty dirs
        #      only when force_clone=True).
        needs_clone = True
        if self.path.exists():
            if not self.path.is_dir():
                raise WikiBackendError(f"GitBackend: local_path is not a directory: {self.path}")
            git_dir = self.path / ".git"
            if git_dir.exists():
                wiped = await self._validate_existing_clone()
                if not wiped:
                    needs_clone = False
            else:
                if any(self.path.iterdir()) and not self.force_clone:
                    raise WikiBackendError(
                        f"GitBackend: {self.path} exists, is non-empty, and is not a git clone. "
                        "Pass force_clone=True after confirming the contents are disposable."
                    )
                if self.force_clone:
                    await self._wipe_path()

        if needs_clone:
            await self._clone()
            await self._configure_identity()
            log_info(f"GitBackend ready (cloned {self.repo_url}@{self.branch}) at {self.path}")
        else:
            await self._configure_identity()
            log_info(f"GitBackend ready (existing clone) at {self.path}")

    async def sync(self) -> None:
        await git_run(
            ["pull", "--rebase", "origin", self.branch],
            cwd=self.path,
            scrubber=self._scrubber,
        )

    async def commit_after_write(self, *, model=None) -> CommitSummary | None:  # noqa: ANN001
        await git_run(["add", "-A"], cwd=self.path, scrubber=self._scrubber)
        # Nothing staged → return early; git would otherwise raise on the commit.
        diff_check = await git_run(
            ["diff", "--cached", "--quiet"],
            cwd=self.path,
            scrubber=self._scrubber,
            check=False,
        )
        if diff_check.returncode == 0:
            log_debug("GitBackend: nothing staged, skipping commit")
            # Still attempt a push to flush any local commits left
            # behind by a previous failed push (e.g. auth recovered
            # since). `git push` with nothing pending is a cheap no-op
            # ("Everything up-to-date"); failures stay debug-level so
            # the agent doesn't see an error for an idle housekeeping
            # call.
            try:
                await git_run(
                    ["push", "origin", self.branch],
                    cwd=self.path,
                    scrubber=self._scrubber,
                )
            except GitError as exc:
                log_debug(f"GitBackend: idle push skipped: {exc}")
            return None

        diff_text = (
            await git_run(
                ["diff", "--cached", "--stat"],
                cwd=self.path,
                scrubber=self._scrubber,
            )
        ).stdout
        diff_full = (
            await git_run(
                ["diff", "--cached"],
                cwd=self.path,
                scrubber=self._scrubber,
            )
        ).stdout

        message = await self.summarize_diff(diff=diff_full or diff_text, model=model)
        await git_run(["commit", "-m", message], cwd=self.path, scrubber=self._scrubber)
        sha = (await git_run(["rev-parse", "HEAD"], cwd=self.path, scrubber=self._scrubber)).stdout.strip()
        files_changed = _count_changed_files(diff_text)

        # Rebase onto whatever landed remotely while we were drafting,
        # then push. If the rebase explodes, abort it cleanly so the
        # working copy is left in a usable state for the next write.
        try:
            await git_run(
                ["pull", "--rebase", "origin", self.branch],
                cwd=self.path,
                scrubber=self._scrubber,
            )
        except GitError as exc:
            log_error(f"GitBackend rebase failed: {exc.stderr}")
            await git_run(
                ["rebase", "--abort"],
                cwd=self.path,
                scrubber=self._scrubber,
                check=False,
            )
            raise WikiBackendError(
                "GitBackend: rebase onto origin failed; commit kept locally but not pushed. "
                f"Run `git pull --rebase` in {self.path} and resolve the conflict."
            ) from exc

        await git_run(
            ["push", "origin", self.branch],
            cwd=self.path,
            scrubber=self._scrubber,
        )
        return CommitSummary(sha=sha, message=message, files_changed=files_changed)

    # -----------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------

    def status(self) -> Status:
        if not self.path.exists():
            return Status(ok=False, detail=f"clone path does not exist: {self.path} (run setup)")
        if not (self.path / ".git").exists():
            return Status(ok=False, detail=f"{self.path} is not a git clone (run setup)")
        return Status(ok=True, detail=f"{self.repo_url}@{self.branch} -> {self.path}")

    async def astatus(self) -> Status:
        return self.status()

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    async def _clone(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await git_run(
            [
                "clone",
                "--branch",
                self.branch,
                "--single-branch",
                self._authenticated_url,
                str(self.path),
            ],
            cwd=self.path.parent,
            scrubber=self._scrubber,
        )
        # `git clone` with an authenticated URL persists the credential
        # in `.git/config`. Rewrite the remote to the bare URL so the
        # token isn't sitting on disk; we re-inject it on each
        # push/pull via the `origin` URL we set below.
        await git_run(
            ["remote", "set-url", "origin", self._authenticated_url],
            cwd=self.path,
            scrubber=self._scrubber,
        )

    async def _validate_existing_clone(self) -> bool:
        """Check the existing clone matches ``repo_url@branch``.

        Returns True if the path was wiped (so the caller should re-clone),
        False if the clone passed validation and was kept in place.
        """
        existing_remote = (
            await git_run(
                ["remote", "get-url", "origin"],
                cwd=self.path,
                scrubber=self._scrubber,
                check=False,
            )
        ).stdout.strip()
        if not _remotes_equivalent(existing_remote, self.repo_url):
            if not self.force_clone:
                raise WikiBackendError(
                    f"GitBackend: existing clone at {self.path} has remote "
                    f"{self._scrubber.scrub(existing_remote)!r} but expected {self.repo_url!r}. "
                    "Pass force_clone=True to wipe and re-clone."
                )
            await self._wipe_path()
            return True

        existing_branch = (
            await git_run(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.path,
                scrubber=self._scrubber,
                check=False,
            )
        ).stdout.strip()
        if existing_branch != self.branch:
            if not self.force_clone:
                raise WikiBackendError(
                    f"GitBackend: existing clone at {self.path} is on branch "
                    f"{existing_branch!r} but expected {self.branch!r}. "
                    "Pass force_clone=True to wipe and re-clone."
                )
            await self._wipe_path()
            return True

        # Refresh credentials in case the PAT was rotated.
        await git_run(
            ["remote", "set-url", "origin", self._authenticated_url],
            cwd=self.path,
            scrubber=self._scrubber,
        )
        return False

    async def _configure_identity(self) -> None:
        await git_run(
            ["config", "user.name", self.author_name],
            cwd=self.path,
            scrubber=self._scrubber,
        )
        await git_run(
            ["config", "user.email", self.author_email],
            cwd=self.path,
            scrubber=self._scrubber,
        )

    async def _wipe_path(self) -> None:
        import shutil

        log_warning(f"GitBackend: wiping {self.path} (force_clone=True)")
        shutil.rmtree(self.path)


# -----------------------------------------------------------------
# Module-level helpers
# -----------------------------------------------------------------


_COMMIT_SUMMARY_INSTRUCTIONS = """\
You write a single-line git commit message for a wiki update.

Constraints:
- Imperative mood (e.g. "Add deploy runbook", not "Added deploy runbook" or "Adds...").
- Under 72 characters.
- No trailing period.
- No leading verbs like "feat:" / "fix:" — this is a wiki, not a code change.
- Describe WHAT changed, not why or how. The diff is the source of truth.

Output ONLY the commit message line. No quotes, no markdown, no backticks.
"""


def _truncate_diff(diff: str, max_chars: int = 8000) -> str:
    if len(diff) <= max_chars:
        return diff
    head = diff[: max_chars // 2]
    tail = diff[-max_chars // 2 :]
    return f"{head}\n... [diff truncated] ...\n{tail}"


def _count_changed_files(stat_output: str) -> int:
    # `git diff --cached --stat` ends with a summary line like
    # ` 3 files changed, 12 insertions(+), 4 deletions(-)`. If that
    # line isn't present (single-file diff), count the body lines.
    summary = re.search(r"\b(\d+) files? changed", stat_output)
    if summary:
        return int(summary.group(1))
    body = [line for line in stat_output.splitlines() if "|" in line]
    return len(body)


def _remotes_equivalent(actual: str, expected: str) -> bool:
    """Compare two remote URLs ignoring trailing ``.git`` and embedded credentials."""
    return _normalise_remote(actual) == _normalise_remote(expected)


def _normalise_remote(url: str) -> str:
    if not url:
        return ""
    out = url.strip()
    if "://" in out:
        scheme, rest = out.split("://", 1)
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        out = f"{scheme.lower()}://{rest}"
    if out.endswith(".git"):
        out = out[:-4]
    return out.rstrip("/")


def _default_clone_path(repo_url: str) -> Path:
    sanitized = re.sub(r"[^a-z0-9]+", "-", _normalise_remote(repo_url).split("/")[-1].lower()).strip("-") or "wiki"
    return Path("/repos") / sanitized
