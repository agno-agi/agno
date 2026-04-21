"""
GitHub Context Provider
=======================

Read-only GitHub access for the calling agent — search repos, read
code, inspect issues and PRs. Writes (create/edit/delete/close) are
filtered out via `include_tools`.

Uses `GITHUB_ACCESS_TOKEN`.
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.tools.github import GithubTools

if TYPE_CHECKING:
    from agno.models.base import Model


READ_ONLY_TOOLS = [
    # Repositories
    "search_repositories",
    "list_repositories",
    "get_repository",
    "get_repository_languages",
    "get_repository_stars",
    "get_repository_with_stats",
    "list_branches",
    # Files / code
    "get_file_content",
    "get_directory_content",
    "get_branch_content",
    "search_code",
    # Issues
    "list_issues",
    "get_issue",
    "list_issue_comments",
    "search_issues_and_prs",
    # Pull requests
    "get_pull_requests",
    "get_pull_request",
    "get_pull_request_count",
    "get_pull_request_changes",
    "get_pull_request_comments",
    "get_pull_request_with_details",
]


class GitHubContextProvider(ContextProvider):
    """Read-only GitHub access."""

    def __init__(
        self,
        *,
        access_token: str | None = None,
        base_url: str | None = None,
        id: str = "github",
        name: str = "GitHub",
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.access_token = access_token or getenv("GITHUB_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("GitHubContextProvider: GITHUB_ACCESS_TOKEN is required")
        self.base_url = base_url
        self._tools: GithubTools | None = None
        self._agent: Agent | None = None

    def status(self) -> Status:
        if not self.access_token:
            return Status(ok=False, detail="GITHUB_ACCESS_TOKEN not set")
        host = self.base_url or "github.com"
        return Status(ok=True, detail=f"github ({host})")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str) -> Answer:
        return answer_from_run(self._ensure_agent().run(question))

    async def aquery(self, question: str) -> Answer:
        return answer_from_run(await self._ensure_agent().arun(question))

    def instructions(self) -> str:
        if self.mode == ContextMode.agent:
            return f"`{self.name}`: call `{self.query_tool_name}(question)` to query GitHub."
        return (
            f"`{self.name}`: `search_repositories` / `search_code` / `search_issues_and_prs` to find. "
            "`get_file_content`, `get_directory_content`, `get_issue`, `get_pull_request_with_details` "
            "to read. Read-only."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return self._all_tools()

    def _all_tools(self) -> list:
        return [self._ensure_tools()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_tools(self) -> GithubTools:
        if self._tools is None:
            self._tools = GithubTools(
                access_token=self.access_token,
                base_url=self.base_url,
                include_tools=READ_ONLY_TOOLS,
            )
        return self._tools

    def _ensure_agent(self) -> Agent:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            role="Answer questions by searching and reading GitHub",
            model=self.model,
            instructions=_AGENT_INSTRUCTIONS,
            tools=[self._ensure_tools()],
            markdown=True,
        )


_AGENT_INSTRUCTIONS = """\
You answer questions by searching and reading GitHub repositories.

Workflow:
1. **Find the right scope.** `search_repositories(query)` to locate repos;
   `search_code(query)` for symbols or patterns across code; `search_issues_and_prs`
   for issue/PR discovery.
2. **Read artifacts.** `get_file_content(repo, path)` for a specific file;
   `get_directory_content` to browse a tree; `get_branch_content` for a whole branch.
3. **Issues and PRs.** `get_issue` / `get_pull_request_with_details` for the body;
   `list_issue_comments` / `get_pull_request_comments` for the discussion.
4. **Cite URLs.** Every claim should include the html_url of what you read.

You are read-only. Never create, edit, close, merge, or delete.
"""
