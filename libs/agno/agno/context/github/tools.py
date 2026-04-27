"""
Git tools for GitHubContextProvider
===================================

Two toolkits:

- :class:`GitReadTools` — log/diff/show/blame/branches over a checkout.
  Side-effect free, used by the read sub-agent.
- :class:`GitWriteTools` — status/add/commit/push and ``gh pr create``,
  scoped to a per-task worktree. Used by the write sub-agent.

Both validate every path stays inside the checkout root and shell out
to ``git`` (and, for the write toolkit, ``gh``) via ``subprocess.run``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from agno.context.github._utils import _run_git
from agno.tools import Toolkit
from agno.utils.log import log_warning

DEFAULT_MAX_OUTPUT_CHARS = 20_000


def _truncate(output: str, limit: int) -> str:
    if len(output) > limit:
        return output[:limit] + f"\n\n... [truncated — output exceeds {limit} chars]"
    return output


class GitReadTools(Toolkit):
    """Read-only git operations over a single checkout.

    All commands run with ``cwd=workdir``. Output is truncated to
    ``max_output_chars`` per call (default 20K) so the sub-agent can't
    be flooded by a multi-megabyte diff.

    :param workdir: Path to the git checkout.
    :param max_output_chars: Truncation limit for tool output. Increase
        for models with larger context windows.
    """

    def __init__(
        self,
        *,
        workdir: Path,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self.workdir = Path(workdir)
        self.max_output_chars = max_output_chars
        super().__init__(
            name="git_read_tools",
            tools=[
                self.git_log,
                self.git_diff,
                self.git_show,
                self.git_branches,
                self.git_blame,
            ],
        )

    def git_log(self, n: int = 20, since: str = "", path: str = "") -> str:
        """Show recent commits as one-line entries.

        :param n: Maximum number of commits to return (default 20).
        :param since: Optional date filter, e.g. ``"2024-01-01"`` or ``"2 weeks ago"``.
        :param path: Optional file/directory path to filter commits to.
        :return: One-line-per-commit log output, or an error message.
        """
        try:
            cmd = ["log", "--oneline", "-n", str(n)]
            if since:
                cmd.append(f"--since={since}")
            if path:
                cmd += ["--", path]
            result = _run_git(cmd, cwd=self.workdir)
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return _truncate(result.stdout.strip(), self.max_output_chars) or "(no commits)"
        except Exception as e:
            log_warning(f"git_log failed: {e}")
            return f"Error: {e}"

    def git_diff(
        self,
        ref1: str,
        ref2: str = "HEAD",
        path: str = "",
        stat: bool = False,
    ) -> str:
        """Show the diff between two refs.

        :param ref1: Starting ref. May contain ``..`` for a range
            (e.g. ``main..feature-x``); ``ref2`` is then ignored.
        :param ref2: Ending ref (default ``HEAD``).
        :param path: Optional path to restrict the diff to.
        :param stat: If True, return ``--stat`` summary instead of full diff.
        :return: Diff text (truncated to ``max_output_chars``), or an error message.
        """
        try:
            if ".." in ref1:
                cmd = ["diff", ref1]
            else:
                cmd = ["diff", f"{ref1}..{ref2}"]
            if stat:
                cmd.append("--stat")
            if path:
                cmd += ["--", path]
            result = _run_git(cmd, cwd=self.workdir)
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return _truncate(result.stdout.strip(), self.max_output_chars) or "(no diff)"
        except Exception as e:
            log_warning(f"git_diff failed: {e}")
            return f"Error: {e}"

    def git_show(self, ref: str) -> str:
        """Show commit metadata and a stat summary for a ref.

        :param ref: Commit hash, branch, or tag.
        :return: Commit info with diffstat (truncated), or an error message.
        """
        try:
            result = _run_git(["show", ref, "--stat"], cwd=self.workdir)
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return _truncate(result.stdout.strip(), self.max_output_chars) or "(no output)"
        except Exception as e:
            log_warning(f"git_show failed: {e}")
            return f"Error: {e}"

    def git_branches(self, remote: bool = True) -> str:
        """List branches.

        :param remote: If True (default), include remote-tracking branches
            (``origin/*``); otherwise list only local branches.
        :return: Branch list, or an error message.
        """
        try:
            cmd = ["branch"]
            if remote:
                cmd.append("-a")
            result = _run_git(cmd, cwd=self.workdir)
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return _truncate(result.stdout.strip(), self.max_output_chars) or "(no branches)"
        except Exception as e:
            log_warning(f"git_branches failed: {e}")
            return f"Error: {e}"

    def git_blame(self, path: str, start_line: int = 1, end_line: int = 50) -> str:
        """Show blame (authorship) for a line range.

        :param path: File path relative to the checkout root.
        :param start_line: First line to blame (default 1).
        :param end_line: Last line to blame (default 50).
        :return: Blame output, or an error message.
        """
        try:
            result = _run_git(
                ["blame", "-L", f"{start_line},{end_line}", path],
                cwd=self.workdir,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return _truncate(result.stdout.strip(), self.max_output_chars) or "(no blame output)"
        except Exception as e:
            log_warning(f"git_blame failed: {e}")
            return f"Error: {e}"


class GitWriteTools(Toolkit):
    """Write-side git + GitHub CLI operations, scoped to a per-task worktree.

    Every push and PR creation validates that the active branch matches
    ``<pr_branch_prefix>/*`` — the tripwire that keeps the agent from
    pushing to ``main`` (or any other un-prefixed branch).

    ``gh`` must be installed on PATH. Auth is propagated by setting
    ``GH_TOKEN`` / ``GITHUB_TOKEN`` in the subprocess env when a token
    was supplied to the constructor.
    """

    # Author identity stamped on commits the sub-agent makes. No global
    # git config required in the container — set per-call via -c flags.
    _COMMIT_AUTHOR_NAME = "Agno"
    _COMMIT_AUTHOR_EMAIL = "agent@agno.ai"

    def __init__(
        self,
        *,
        workdir: Path,
        task_workdir: Path,
        pr_branch_prefix: str,
        base_branch: str,
        github_token: Optional[str] = None,
        gh_path: Optional[str] = None,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self.workdir = Path(workdir).resolve()
        self.task_workdir = Path(task_workdir).resolve()
        self.pr_branch_prefix = pr_branch_prefix
        self.base_branch = base_branch
        self.github_token = github_token
        self.max_output_chars = max_output_chars
        # Defer `gh` lookup so tests can stub via PATH and so a missing
        # `gh` only blocks PR-time, not toolkit construction.
        self.gh_path = gh_path or "gh"

        # Path-escape protection: the worktree must live inside the main
        # checkout. This mirrors Coda's _repo_path validator.
        if not self.task_workdir.is_relative_to(self.workdir):
            raise ValueError(f"task_workdir {self.task_workdir} is not inside workdir {self.workdir}")

        super().__init__(
            name="git_write_tools",
            tools=[
                self.git_status,
                self.git_add,
                self.git_commit,
                self.git_push,
                self.create_pull_request,
                self.pr_status,
            ],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_branch(self) -> str:
        result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=self.task_workdir)
        return result.stdout.strip()

    def _validate_branch(self, branch: str) -> Optional[str]:
        """Return an error string if ``branch`` may not be pushed, else ``None``."""
        if not branch:
            return "Error: could not determine current branch (detached HEAD?)"
        prefix = f"{self.pr_branch_prefix}/"
        if not branch.startswith(prefix):
            return f"Error: refusing to push branch '{branch}'. Only '{prefix}*' branches can be pushed."
        return None

    def _gh_env(self) -> dict:
        """Subprocess env for ``gh`` calls — propagates GH_TOKEN/GITHUB_TOKEN."""
        env = dict(os.environ)
        if self.github_token:
            env["GH_TOKEN"] = self.github_token
            env["GITHUB_TOKEN"] = self.github_token
        return env

    def _run_gh(
        self,
        args: List[str],
        *,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.gh_path, *args],
            capture_output=True,
            text=True,
            cwd=str(self.task_workdir),
            timeout=timeout,
            env=self._gh_env(),
        )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def git_status(self) -> str:
        """Show the short porcelain status of the worktree.

        :return: Output of ``git status --short``, or an error message.
        """
        try:
            result = _run_git(["status", "--short"], cwd=self.task_workdir)
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return _truncate(result.stdout, self.max_output_chars) or "(clean)"
        except Exception as e:
            log_warning(f"git_status failed: {e}")
            return f"Error: {e}"

    def git_add(self, paths: Optional[List[str]] = None) -> str:
        """Stage paths.

        :param paths: List of paths relative to the worktree. Defaults to
            ``["-A"]`` (stage everything).
        :return: Confirmation message, or an error message.
        """
        try:
            args = list(paths) if paths else ["-A"]
            result = _run_git(["add", *args], cwd=self.task_workdir)
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return f"Staged: {', '.join(args)}"
        except Exception as e:
            log_warning(f"git_add failed: {e}")
            return f"Error: {e}"

    def git_commit(self, message: str) -> str:
        """Create a commit with the staged changes.

        Author identity is set per-call so the container doesn't need
        global git config.

        :param message: Commit message.
        :return: Confirmation message with the new short SHA, or an error.
        """
        try:
            if not message or not message.strip():
                return "Error: commit message cannot be empty"
            result = _run_git(
                [
                    "-c",
                    f"user.name={self._COMMIT_AUTHOR_NAME}",
                    "-c",
                    f"user.email={self._COMMIT_AUTHOR_EMAIL}",
                    "commit",
                    "-m",
                    message,
                ],
                cwd=self.task_workdir,
            )
            if result.returncode != 0:
                # `git commit` writes the "nothing to commit" notice to
                # stdout, not stderr — surface whichever is non-empty.
                err = result.stderr.strip() or result.stdout.strip()
                return f"Error: {err}"
            sha_result = _run_git(["rev-parse", "--short", "HEAD"], cwd=self.task_workdir)
            sha = sha_result.stdout.strip()
            return f"Committed {sha}: {message}"
        except Exception as e:
            log_warning(f"git_commit failed: {e}")
            return f"Error: {e}"

    def git_push(self, branch: str = "") -> str:
        """Push a branch to ``origin``. Refuses non-prefixed branches.

        :param branch: Branch name to push. Defaults to the current branch
            of the worktree.
        :return: Confirmation message, or an error.
        """
        try:
            target = branch or self._current_branch()
            err = self._validate_branch(target)
            if err:
                return err
            result = _run_git(
                ["push", "-u", "origin", target],
                cwd=self.task_workdir,
                timeout=120,
            )
            if result.returncode != 0:
                return f"Error pushing: {result.stderr.strip()}"
            return f"Pushed {target} to origin."
        except Exception as e:
            log_warning(f"git_push failed: {e}")
            return f"Error: {e}"

    def create_pull_request(self, title: str, body: str, branch: str = "") -> str:
        """Open a pull request via the ``gh`` CLI.

        Requires ``gh`` on PATH. Uses ``GH_TOKEN`` / ``GITHUB_TOKEN``
        from this toolkit's constructor (or the inherited environment).

        :param title: PR title.
        :param body: PR body (markdown).
        :param branch: Head branch. Defaults to the current branch.
        :return: PR URL on success, or an error message.
        """
        try:
            if shutil.which(self.gh_path) is None:
                return (
                    f"Error: '{self.gh_path}' not found on PATH. Install the GitHub CLI "
                    "(https://cli.github.com/) to enable create_pull_request."
                )
            target = branch or self._current_branch()
            err = self._validate_branch(target)
            if err:
                return err
            result = self._run_gh(
                [
                    "pr",
                    "create",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--head",
                    target,
                    "--base",
                    self.base_branch,
                ]
            )
            if result.returncode != 0:
                return f"Error creating PR: {result.stderr.strip() or result.stdout.strip()}"
            # gh prints the URL on its own line.
            return result.stdout.strip() or "(PR created — gh returned no URL)"
        except Exception as e:
            log_warning(f"create_pull_request failed: {e}")
            return f"Error: {e}"

    def pr_status(self, branch: str = "") -> str:
        """Look up the PR (if any) for a branch via ``gh pr view``.

        :param branch: Branch name. Defaults to the current branch.
        :return: JSON with ``url``, ``state``, ``title`` keys, or an
            error / "no pr found" message.
        """
        try:
            if shutil.which(self.gh_path) is None:
                return f"Error: '{self.gh_path}' not found on PATH."
            target = branch or self._current_branch()
            if not target:
                return "Error: could not determine branch"
            result = self._run_gh(["pr", "view", target, "--json", "url,state,title"])
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                # gh exits non-zero with "no pull requests found" when there's nothing.
                if "no pull requests found" in err.lower() or "no open pull requests" in err.lower():
                    return f"(no PR found for {target})"
                return f"Error: {err}"
            try:
                payload: Any = json.loads(result.stdout)
                return json.dumps(payload, indent=2)
            except json.JSONDecodeError:
                return result.stdout.strip()
        except Exception as e:
            log_warning(f"pr_status failed: {e}")
            return f"Error: {e}"
