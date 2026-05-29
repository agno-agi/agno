"""
WikiBackend — pluggable I/O layer behind WikiContextProvider.
=============================================================

The provider owns the agent-facing contract (two tools, two sub-agents).
The backend owns the on-disk wiki directory and any synchronisation
with an external store. Backends that ship today:

- ``FileSystemBackend`` — the directory is the source of truth. ``sync``
  and ``commit_after_write`` are no-ops. Demoable with no auth, no
  network. The path that proves the design works.
- ``GitBackend`` — the directory is a clone of a remote git repo. ``sync``
  pulls; ``commit_after_write`` stages, commits, rebases on top of the
  remote, and pushes. PAT auth via ``github_token``.
- ``NotionDatabaseBackend`` — the directory mirrors rows of a Notion
  database as markdown files with frontmatter (page id, last edited).
  ``sync`` wipes the mirror and rebuilds from Notion; ``commit_after_write``
  parses local files, pushes block updates, creates new pages, and
  archives pages whose files were deleted. Integration-token auth.
- ``NotionPageBackend`` — planned for v2 (root page -> nested directory
  tree). Stub today.

All backends expose the same surface so the provider doesn't branch on
backend type; new backends (S3, GitHub App auth, etc.) can drop in
without touching ``WikiContextProvider``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agno.context.provider import Status
from agno.context.wiki.git_ops import GitError, Scrubber, build_authenticated_url
from agno.context.wiki.git_ops import run as git_run
from agno.context.wiki.notion_ops import (
    Frontmatter,
    Manifest,
    blocks_to_markdown,
    markdown_to_blocks,
    page_filename,
    parse_page_file,
    render_page_file,
)
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
        return await asyncio.to_thread(self.status)

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
        return await asyncio.to_thread(self.status)

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


# -----------------------------------------------------------------
# Notion backends
# -----------------------------------------------------------------


class NotionDatabaseBackend(WikiBackend):
    """Wiki backend backed by a single Notion database.

    Each row of the database is mirrored as one ``<kebab-title>.md``
    file under ``self.path``, with frontmatter recording the page id
    and last-edited timestamp:

        ---
        notion_page_id: 8a7c2f3e-...
        notion_last_edited: 2026-05-13T10:22:00Z
        title: Deploy Runbook
        ---

        # Deploy Runbook
        ...

    Notion is the source of truth. ``sync`` wipes the local ``*.md``
    files and rebuilds them from the database. ``commit_after_write``
    walks the directory, pushes block updates for changed files,
    creates pages for new files, and archives pages whose files were
    deleted locally. Non-markdown files are left untouched on both
    paths so user-side state in the directory survives a sync.

    Auth is an integration token (Notion -> Settings -> Connections).
    Pass ``token`` directly or set ``NOTION_API_KEY``. The integration
    must be added to the database via the database page's
    "Connections" menu.

    Conflict policy: if a page was edited inside Notion after the last
    sync, ``commit_after_write`` raises ``WikiBackendError`` rather
    than overwriting. Call ``wiki.sync()`` and retry.

    API version: targets Notion API ``2025-09-03`` (the notion-client
    3.1.0 default), which routes page queries and the new-page parent
    through *data sources* rather than the database itself. The
    backend resolves and caches the first data source on ``setup``;
    multi-source databases are not yet supported (a warning is logged
    and the first source is used).

    Block subset (round-trip): paragraphs, H1-H3, bulleted / numbered
    lists, todos, quotes, fenced code, dividers. Other block types
    (toggles, callouts, tables, images, embeds, child pages) render as
    a comment placeholder on read and are not produced on write.
    """

    def __init__(
        self,
        *,
        database_id: str,
        token: str | None = None,
        local_path: Path | str | None = None,
    ) -> None:
        resolved = token or os.getenv("NOTION_API_KEY")
        if not resolved:
            raise ValueError("NotionDatabaseBackend: pass token=... or set NOTION_API_KEY")
        if not database_id:
            raise ValueError("NotionDatabaseBackend: database_id is required")
        self.database_id: str = database_id
        self.token: str = resolved
        path = Path(local_path).expanduser().resolve() if local_path else _default_notion_path(database_id)
        super().__init__(path=path)
        self._title_property: str | None = None
        # Notion API ``2025-09-03`` (the notion-client 3.1.0 default) moved
        # the property schema and page queries from databases to *data
        # sources*. A database has one or more data sources; for the
        # single-source case (overwhelmingly the common one) we cache the
        # id here and route ``query`` / ``create_page`` through it.
        self._data_source_id: str | None = None
        self._client: Any = None

    @property
    def manifest_path(self) -> Path:
        return self.path / ".notion-sync.json"

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def setup(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        client = self._get_client()
        try:
            db = await client.databases.retrieve(database_id=self.database_id)
        except Exception as exc:
            raise WikiBackendError(
                f"NotionDatabaseBackend: cannot reach database {self.database_id}. "
                "Check that the integration is invited via the database's Connections menu. "
                f"Underlying error: {type(exc).__name__}: {exc}"
            ) from exc
        # Under API ``2025-09-03`` the database object carries a ``data_sources``
        # list; the column schema lives on each data source, not on the database.
        # Resolve the first source and warn on multi-source DBs (rare today).
        data_sources = db.get("data_sources") or []
        if not data_sources:
            raise WikiBackendError(
                f"NotionDatabaseBackend: database {self.database_id} has no data sources. "
                "This usually means the integration is missing access — re-check the "
                "database's Connections menu."
            )
        if len(data_sources) > 1:
            log_warning(
                f"NotionDatabaseBackend: database {self.database_id} has "
                f"{len(data_sources)} data sources; using the first ({data_sources[0].get('id')}). "
                "Multi-source databases are not yet supported."
            )
        self._data_source_id = data_sources[0]["id"]

        try:
            source = await client.data_sources.retrieve(data_source_id=self._data_source_id)
        except Exception as exc:
            raise WikiBackendError(
                f"NotionDatabaseBackend: cannot read data source {self._data_source_id} "
                f"on database {self.database_id}. Underlying error: {type(exc).__name__}: {exc}"
            ) from exc
        # Discover the title column. Every Notion data source has exactly one
        # property with type=="title"; users name it whatever they like
        # ("Name", "Title", "Page", ...) so we can't hard-code the key.
        for prop_name, prop in (source.get("properties") or {}).items():
            if prop.get("type") == "title":
                self._title_property = prop_name
                break
        if self._title_property is None:
            raise WikiBackendError(f"NotionDatabaseBackend: data source {self._data_source_id} has no title property")
        log_info(
            f"NotionDatabaseBackend ready (db={self.database_id}, "
            f"data_source={self._data_source_id}, title_prop={self._title_property!r}) at {self.path}"
        )

    async def sync(self) -> None:
        if self._title_property is None:
            await self.setup()
        client = self._get_client()
        pages = await self._query_all_pages(client)
        used_names: set[str] = set()
        new_manifest = Manifest()
        for page in pages:
            page_id = page["id"]
            title = self._extract_title(page)
            last_edited = page.get("last_edited_time", "")
            blocks = await self._fetch_blocks(client, page_id)
            body = blocks_to_markdown(blocks)
            filename = page_filename(title, page_id, used=used_names)
            used_names.add(filename)
            text = render_page_file(
                title=title,
                page_id=page_id,
                last_edited=last_edited,
                body=body,
            )
            (self.path / filename).write_text(text, encoding="utf-8")
            new_manifest.entries[filename] = page_id
        # Prune local ``*.md`` files that aren't in the new snapshot.
        # Non-md files are left in place -- the user may keep notes,
        # gitignore, etc. alongside the mirror.
        for existing in self.path.glob("*.md"):
            if existing.name not in new_manifest.entries:
                existing.unlink()
        new_manifest.save(self.manifest_path)
        log_debug(f"NotionDatabaseBackend: synced {len(new_manifest.entries)} page(s) to {self.path}")

    async def commit_after_write(self, *, model=None) -> CommitSummary | None:  # noqa: ANN001
        if self._title_property is None:
            await self.setup()
        client = self._get_client()
        manifest = Manifest.load(self.manifest_path)
        prior = dict(manifest.entries)
        seen: dict[str, str] = {}
        changes: list[str] = []
        for path in sorted(self.path.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            fm, body = parse_page_file(text)
            blocks = markdown_to_blocks(body)
            if fm.notion_page_id:
                await self._update_page(client, fm, blocks)
                seen[path.name] = fm.notion_page_id
                changes.append(f"updated {path.name}")
            else:
                new_id = await self._create_page(client, fm.title or path.stem.replace("-", " ").title(), blocks)
                seen[path.name] = new_id
                changes.append(f"created {path.name}")
        # Files that were in the prior manifest but not in this commit
        # were deleted locally -> archive on Notion.
        for filename, page_id in prior.items():
            if filename in seen:
                continue
            await client.pages.update(page_id=page_id, archived=True)
            changes.append(f"archived {filename}")
        if not changes:
            return None
        # Re-sync so the next commit sees fresh ``notion_last_edited``
        # timestamps. Cheaper than splicing each frontmatter by hand.
        await self.sync()
        message = await self.summarize_diff(diff="\n".join(changes), model=model)
        return CommitSummary(
            sha=_pseudo_sha(changes),
            message=message,
            files_changed=len(changes),
        )

    # -----------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------

    def status(self) -> Status:
        if not self.path.exists():
            return Status(ok=False, detail=f"local mirror missing: {self.path} (run setup)")
        return Status(ok=True, detail=f"notion db {self.database_id} -> {self.path}")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from notion_client import AsyncClient
            except ImportError as exc:  # pragma: no cover - import-time guard
                raise WikiBackendError(
                    "NotionDatabaseBackend requires the 'notion-client' package. "
                    "Install with `pip install notion-client`."
                ) from exc
            self._client = AsyncClient(auth=self.token)
        return self._client

    async def _query_all_pages(self, client: Any) -> list[dict[str, Any]]:
        assert self._data_source_id is not None, "setup() must populate _data_source_id"
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"data_source_id": self._data_source_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await client.data_sources.query(**kwargs)
            pages.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return pages

    async def _fetch_blocks(self, client: Any, page_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await client.blocks.children.list(**kwargs)
            out.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return out

    def _extract_title(self, page: dict[str, Any]) -> str:
        props = page.get("properties") or {}
        title_prop = props.get(self._title_property or "", {})
        rich = title_prop.get("title", []) or []
        title = "".join(span.get("plain_text", "") for span in rich)
        return title or "Untitled"

    async def _update_page(
        self,
        client: Any,
        fm: Frontmatter,
        new_blocks: list[dict[str, Any]],
    ) -> None:
        # Caller only routes existing pages here; the truthiness check
        # lives in ``commit_after_write``. Re-assert for the type checker.
        assert fm.notion_page_id is not None
        page_id: str = fm.notion_page_id
        page = await client.pages.retrieve(page_id=page_id)
        remote_edited = page.get("last_edited_time", "")
        # Conflict check: if Notion was edited since our last sync, refuse.
        if fm.notion_last_edited and remote_edited and remote_edited > fm.notion_last_edited:
            raise WikiBackendError(
                f"NotionDatabaseBackend: page id={page_id} title={fm.title!r} was edited "
                f"in Notion since the last sync ({fm.notion_last_edited} -> {remote_edited}). "
                "Refusing to overwrite. Run wiki.sync() and retry."
            )
        # Rename if the frontmatter title changed.
        current_title = self._extract_title(page)
        if fm.title and fm.title != current_title:
            await client.pages.update(
                page_id=page_id,
                properties={
                    self._title_property: {  # type: ignore[dict-item]
                        "title": [{"type": "text", "text": {"content": fm.title}}]
                    }
                },
            )
        # Wholesale block replacement. Diffing block trees is its own
        # project; archive-all then append matches the agent's mental
        # model ("here's the new body").
        existing = await self._fetch_blocks(client, page_id)
        for block in existing:
            try:
                await client.blocks.delete(block_id=block["id"])
            except Exception as exc:
                log_warning(f"NotionDatabaseBackend: failed to delete block {block['id']}: {exc}")
        if new_blocks:
            # Notion caps a single ``append`` at 100 children. Chunk to be safe.
            for chunk_start in range(0, len(new_blocks), 100):
                await client.blocks.children.append(
                    block_id=page_id,
                    children=new_blocks[chunk_start : chunk_start + 100],
                )

    async def _create_page(self, client: Any, title: str, blocks: list[dict[str, Any]]) -> str:
        assert self._data_source_id is not None, "setup() must populate _data_source_id"
        first_chunk = blocks[:100]
        created = await client.pages.create(
            # Under API 2025-09-03 the parent for a new page in a database
            # is the data source, not the database itself.
            parent={"type": "data_source_id", "data_source_id": self._data_source_id},
            properties={
                self._title_property: {  # type: ignore[dict-item]
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
            children=first_chunk,
        )
        page_id = created["id"]
        for chunk_start in range(100, len(blocks), 100):
            await client.blocks.children.append(
                block_id=page_id,
                children=blocks[chunk_start : chunk_start + 100],
            )
        return page_id


class NotionPageBackend(WikiBackend):
    """Root Notion page -> nested directory tree. Planned for v2.

    The flat database mode (``NotionDatabaseBackend``) ships today. The
    nested mode covers a Notion page hierarchy: subpages become folders,
    block subtrees walk recursively, and the supported block subset
    grows (toggles, callouts, tables, images). Use the database backend
    until this is implemented.
    """

    def __init__(
        self,
        *,
        root_page_id: str,  # noqa: ARG002 - documents the future signature
        token: str | None = None,  # noqa: ARG002
        local_path: Path | str | None = None,  # noqa: ARG002
    ) -> None:
        raise NotImplementedError(
            "NotionPageBackend (nested mode) is on the roadmap. "
            "Use NotionDatabaseBackend for a flat database-backed wiki today."
        )

    async def setup(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def sync(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def commit_after_write(self, *, model=None) -> CommitSummary | None:  # noqa: ANN001  # pragma: no cover - stub
        raise NotImplementedError


def _default_notion_path(database_id: str) -> Path:
    return Path("/repos") / f"notion-{database_id.replace('-', '')[:8]}"


def _pseudo_sha(changes: list[str]) -> str:
    """Synthetic sha so ``CommitSummary`` stays a uniform shape across backends.

    Notion has no commit hash -- we hash the change list so log lines
    are unique per write. Truncated to 40 chars to match git's display.
    """
    return hashlib.sha1("\n".join(changes).encode("utf-8")).hexdigest()
