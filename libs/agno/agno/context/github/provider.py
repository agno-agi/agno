"""
GitHub Context Provider
=======================

Read + write access to a Git repository hosted on GitHub via two tools:

- ``query_<id>`` — natural-language reads against a checkout (file
  navigation + git log/diff/blame), backed by a sub-agent with
  read-only Workspace + git tools.
- ``update_<id>`` — natural-language writes that end in a pull
  request, backed by a sub-agent with full Workspace + git tools
  scoped to a per-session worktree.

The write sub-agent never operates on the main checkout — every
session gets its own ``<workdir>/worktrees/<task>/`` worktree on a
``<prefix>/<task>`` branch. ``git push`` and ``gh pr create`` refuse
any branch that doesn't match the prefix, so the agent can't push
to the default branch.

Authentication: ``github_token`` kwarg, or ``GITHUB_TOKEN`` env var.
The token is embedded into the clone URL as
``https://x-access-token:<token>@github.com/...`` so subsequent
pushes use it without further setup. ``gh`` calls receive the same
token via ``GH_TOKEN`` / ``GITHUB_TOKEN`` env.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.github.tools import GitReadTools, GitWriteTools, _run_git
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.workspace import Workspace
from agno.utils.log import log_info, log_warning

if TYPE_CHECKING:
    from agno.models.base import Model


# Sanitizer for session_id → safe task name component. Keeps alnum,
# underscore, and dash; collapses everything else to '-'; caps length.
_TASK_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_-]+")
_TASK_MAX_LEN = 40


def _parse_repo(repo: str) -> tuple[str, str]:
    """Parse "owner/name" or a full https URL into (owner, name).

    Strips a trailing ``.git`` and any leading ``https://github.com/``.
    """
    cleaned = repo.strip()
    cleaned = re.sub(r"^https?://github\.com/", "", cleaned)
    cleaned = re.sub(r"\.git$", "", cleaned)
    parts = cleaned.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"GitHubContextProvider: could not parse repo '{repo}'. "
            "Expected 'owner/name' or 'https://github.com/owner/name'."
        )
    return parts[0], parts[1]


def _sanitize_task(raw: str) -> str:
    """Turn a session_id (or any string) into a path/branch-safe task token."""
    s = _TASK_SANITIZE_RE.sub("-", raw).strip("-")
    if not s:
        return uuid.uuid4().hex[:8]
    return s[:_TASK_MAX_LEN]


class GitHubContextProvider(ContextProvider):
    """Workspace + git navigation over a GitHub repo, with edit-via-PR writes."""

    def __init__(
        self,
        *,
        repo: str,
        root: str | Path = "/repos",
        branch: str = "main",
        github_token: Optional[str] = None,
        pr_branch_prefix: str = "agno",
        id: str = "github",
        name: str = "GitHub",
        read_instructions: Optional[str] = None,
        write_instructions: Optional[str] = None,
        mode: ContextMode = ContextMode.default,
        model: Optional[Model] = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        owner, repo_name = _parse_repo(repo)
        self.owner = owner
        self.repo_name = repo_name
        self.repo = f"{owner}/{repo_name}"
        self.root = Path(root).expanduser().resolve()
        self.workdir: Path = self.root / repo_name
        self.branch = branch
        self.github_token = github_token
        self.pr_branch_prefix = pr_branch_prefix
        self.read_instructions_text = (
            read_instructions if read_instructions is not None else DEFAULT_GITHUB_READ_INSTRUCTIONS
        )
        self.write_instructions_text = (
            write_instructions if write_instructions is not None else DEFAULT_GITHUB_WRITE_INSTRUCTIONS
        )
        # Lazily built. The read agent is shared across sessions; write
        # agents are keyed by session_id because each session has its
        # own worktree.
        self._read_agent: Optional[Agent] = None
        self._write_agents: dict[str, Agent] = {}
        self._task_workdirs: dict[str, Path] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def asetup(self) -> None:
        """Clone the repo (or fetch+pull an existing checkout). Idempotent."""
        if self.github_token is None:
            self.github_token = os.environ.get("GITHUB_TOKEN")

        if self.workdir.exists() and (self.workdir / ".git").exists():
            self._refresh_existing_checkout()
        else:
            self._clone_fresh()

    def _refresh_existing_checkout(self) -> None:
        # Fetch + checkout + ff-only pull. If pull fails (typically dirty
        # tree or diverged branch), warn but don't fail — the agent can
        # still see the state via git_status and decide.
        fetch = _run_git(["fetch", "origin"], cwd=self.workdir, timeout=120)
        if fetch.returncode != 0:
            log_warning(f"git fetch in {self.workdir} returned non-zero: {fetch.stderr.strip()}")

        co = _run_git(["checkout", self.branch], cwd=self.workdir)
        if co.returncode != 0:
            log_warning(f"git checkout {self.branch} returned non-zero: {co.stderr.strip()}")

        pull = _run_git(
            ["pull", "--ff-only", "origin", self.branch],
            cwd=self.workdir,
            timeout=120,
        )
        if pull.returncode != 0:
            status = _run_git(["status", "--short"], cwd=self.workdir)
            log_warning(
                f"git pull --ff-only failed in {self.workdir}: {pull.stderr.strip()}. "
                f"git status:\n{status.stdout.strip()}"
            )

    def _clone_fresh(self) -> None:
        self.workdir.parent.mkdir(parents=True, exist_ok=True)
        clone_url = self._build_clone_url()
        clone = _run_git(
            ["clone", clone_url, str(self.workdir)],
            cwd=self.workdir.parent,
            timeout=300,
        )
        if clone.returncode != 0:
            err = clone.stderr.strip()
            # Don't leak the token if it ended up echoed in stderr.
            if self.github_token:
                err = err.replace(self.github_token, "***")
            if self.github_token is None:
                raise RuntimeError(f"Failed to clone {self.repo}: {err}. If this is a private repo, set GITHUB_TOKEN.")
            raise RuntimeError(f"Failed to clone {self.repo}: {err}")

        co = _run_git(["checkout", self.branch], cwd=self.workdir)
        if co.returncode != 0:
            log_warning(f"checkout {self.branch} after clone returned: {co.stderr.strip()}")

    def _build_clone_url(self) -> str:
        if self.github_token:
            return f"https://x-access-token:{self.github_token}@github.com/{self.repo}.git"
        return f"https://github.com/{self.repo}.git"

    async def aclose(self) -> None:
        """Best-effort teardown of every worktree this provider created."""
        if not self.workdir.exists():
            return
        for session_id, path in list(self._task_workdirs.items()):
            self._remove_worktree(session_id, path)
        self._task_workdirs.clear()
        self._write_agents.clear()

    def _remove_worktree(self, session_id: str, path: Path) -> None:
        try:
            _run_git(["worktree", "remove", str(path), "--force"], cwd=self.workdir)
            task = _sanitize_task(session_id)
            _run_git(["branch", "-D", f"{self.pr_branch_prefix}/{task}"], cwd=self.workdir)
        except Exception as e:
            log_warning(f"failed to clean up worktree {path}: {e}")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Status:
        if not self.workdir.exists():
            return Status(
                ok=False,
                detail=f"workdir not initialized: {self.workdir} (asetup() not run yet)",
            )
        if not (self.workdir / ".git").exists():
            return Status(ok=False, detail=f"not a git repo: {self.workdir}")
        try:
            branch = _run_git(["branch", "--show-current"], cwd=self.workdir).stdout.strip()
            sha = _run_git(["rev-parse", "--short", "HEAD"], cwd=self.workdir).stdout.strip()
        except Exception as e:
            return Status(ok=False, detail=f"git error: {e}")
        return Status(
            ok=True,
            detail=f"{self.repo}@{branch or '(detached)'}:{sha or 'no-commits'}",
        )

    async def astatus(self) -> Status:
        return self.status()

    # ------------------------------------------------------------------
    # Query / update
    # ------------------------------------------------------------------

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_read_agent().run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_read_agent().arun(question, **kwargs))

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        session_id, ephemeral = self._session_key(run_context)
        agent = self._ensure_write_agent(session_id)
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        try:
            return answer_from_run(agent.run(instruction, **kwargs))
        finally:
            if ephemeral:
                self._teardown_session(session_id)

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        session_id, ephemeral = self._session_key(run_context)
        agent = self._ensure_write_agent(session_id)
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        try:
            return answer_from_run(await agent.arun(instruction, **kwargs))
        finally:
            if ephemeral:
                self._teardown_session(session_id)

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: navigate {self.repo}@{self.branch} via Workspace "
                "(`read_file` / `list_files` / `search_content`) plus read-only git tools "
                "(`git_log`, `git_diff`, `git_show`, `git_branches`, `git_blame`). "
                "mode=tools is read-only — writes require mode=default (two-tool surface)."
            )
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to read {self.repo}, "
            f"or `{self.update_tool_name}(instruction)` to make changes. Updates run on a "
            f"`{self.pr_branch_prefix}/<task>` branch and end in a pull request — the human "
            "reviews and merges; the agent never pushes to the default branch."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return [self._query_tool(), self._update_tool()]

    def _all_tools(self) -> list:
        # Read-only flat surface. Writes require the sub-agent split:
        # they need a worktree per call, which the flat surface can't
        # express cleanly without smuggling session_id into every tool.
        return [
            Workspace(root=self.workdir, allowed=Workspace.READ_TOOLS, confirm=[]),
            GitReadTools(workdir=self.workdir),
        ]

    # ------------------------------------------------------------------
    # Sub-agents
    # ------------------------------------------------------------------

    def _ensure_read_agent(self) -> Agent:
        if self._read_agent is None:
            self._read_agent = self._build_read_agent()
        return self._read_agent

    def _build_read_agent(self) -> Agent:
        return Agent(
            id=f"{self.id}-read",
            name=f"{self.name} Read",
            model=self.model,
            instructions=self.read_instructions_text.replace("{repo}", self.repo).replace("{branch}", self.branch),
            tools=[
                Workspace(root=self.workdir, allowed=Workspace.READ_TOOLS, confirm=[]),
                GitReadTools(workdir=self.workdir),
            ],
            markdown=True,
        )

    def _ensure_write_agent(self, session_id: str) -> Agent:
        if session_id in self._write_agents:
            return self._write_agents[session_id]
        task_workdir = self._ensure_task_workdir(session_id)
        agent = self._build_write_agent(task_workdir)
        self._write_agents[session_id] = agent
        return agent

    def _build_write_agent(self, task_workdir: Path) -> Agent:
        return Agent(
            id=f"{self.id}-write",
            name=f"{self.name} Write",
            model=self.model,
            instructions=self.write_instructions_text.replace("{repo}", self.repo)
            .replace("{branch}", self.branch)
            .replace("{base_branch}", self.branch)
            .replace("{prefix}", self.pr_branch_prefix),
            tools=[
                Workspace(root=task_workdir, allowed=Workspace.ALL_TOOLS, confirm=[]),
                GitWriteTools(
                    workdir=self.workdir,
                    task_workdir=task_workdir,
                    pr_branch_prefix=self.pr_branch_prefix,
                    base_branch=self.branch,
                    github_token=self.github_token,
                ),
            ],
            markdown=True,
        )

    # ------------------------------------------------------------------
    # Worktree lifecycle
    # ------------------------------------------------------------------

    def _session_key(self, run_context: RunContext | None) -> tuple[str, bool]:
        """Pick the dict key for this update call.

        Returns ``(key, ephemeral)``. When the caller didn't propagate a
        ``session_id``, we synthesize one and tear the worktree down
        after the call so single-shot programmatic use doesn't leak
        state.
        """
        sid = getattr(run_context, "session_id", None) if run_context else None
        if sid:
            return sid, False
        return f"_ephemeral-{uuid.uuid4().hex[:8]}", True

    def _ensure_task_workdir(self, session_id: str) -> Path:
        if session_id in self._task_workdirs:
            return self._task_workdirs[session_id]

        task = _sanitize_task(session_id)
        worktree_path = self.workdir / "worktrees" / task
        branch_name = f"{self.pr_branch_prefix}/{task}"

        # Refresh refs so the worktree branches off the latest base.
        fetch = _run_git(["fetch", "origin"], cwd=self.workdir, timeout=120)
        if fetch.returncode != 0:
            log_warning(f"fetch before worktree create returned: {fetch.stderr.strip()}")

        # Branch from origin/<base_branch> when available, fall back to
        # local <base_branch> for tests against a fake remote.
        base_ref = f"origin/{self.branch}"
        check_remote = _run_git(["rev-parse", "--verify", base_ref], cwd=self.workdir)
        if check_remote.returncode != 0:
            base_ref = self.branch

        result = _run_git(
            ["worktree", "add", str(worktree_path), "-b", branch_name, base_ref],
            cwd=self.workdir,
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to create worktree at {worktree_path}: {result.stderr.strip()}")

        self._task_workdirs[session_id] = worktree_path
        log_info(f"created worktree for session {session_id}: {worktree_path}")
        return worktree_path

    def _teardown_session(self, session_id: str) -> None:
        path = self._task_workdirs.pop(session_id, None)
        self._write_agents.pop(session_id, None)
        if path is not None:
            self._remove_worktree(session_id, path)


DEFAULT_GITHUB_READ_INSTRUCTIONS = """\
You answer questions by navigating the `{repo}` repository at branch `{branch}`.

## Workflow

1. **Start broad.** `list_files` to see top-level layout, or
   `search_files` with a glob (`**/*.py`, `docs/*`) to narrow.
2. **Find content.** `search_content(query)` surfaces files whose text
   matches — much faster than reading speculatively.
3. **Read precisely.** `read_file` returns line-numbered output. For
   large files, pass `start_line` / `end_line`.
4. **Use git history when the question is about *change*.** `git_log`
   for recent commits, `git_diff` for what changed between refs,
   `git_show` for a single commit, `git_blame` for line authorship.
5. **Cite the paths.** Every claim points to a file path. When
   quoting, use exact text — don't paraphrase.

You are read-only. To request a change, the calling agent uses the
separate update tool — explain that and stop.
"""


DEFAULT_GITHUB_WRITE_INSTRUCTIONS = """\
You make changes to `{repo}` on a `{prefix}/<task>` branch and open a
pull request when the task is done.

## Workflow

1. **Read the affected files first.** Don't edit code you haven't
   read this session — `read_file` (with line numbers) gives you the
   exact context for an edit.
2. **Make minimal edits.** `edit_file` for targeted substring
   replacements, `write_file` to create new files. Keep the diff
   focused on the task.
3. **Stage + commit.** `git_add` (defaults to "-A") then `git_commit`
   with a clear, imperative subject.
4. **Push.** `git_push` sends the branch to origin. Only
   `{prefix}/*` branches can be pushed.
5. **Open the PR.** `create_pull_request(title, body)` ends the
   task — the human reviews and merges. Don't combine unrelated
   changes into one PR.

## When iterating on the same task

If you're continuing from a previous turn (same session), keep
committing to the same branch. The next push updates the existing
PR — there's no need to open a new one.

## Don'ts

- Don't push directly to `{base_branch}`.
- Don't create commits without reading the affected files in this
  session first — even if the file looks familiar.
- Don't open a second PR for the same task.
"""
