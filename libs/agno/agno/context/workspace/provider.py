"""
Workspace Context Provider
==========================

Exposes a local project workspace via a read-only `Workspace` toolkit.
The provider is intended for repository roots and other working trees
where dependency directories, build outputs, and agent scratch folders
should be ignored by default.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.workspace import DEFAULT_EXCLUDE_PATTERNS, Workspace

if TYPE_CHECKING:
    from agno.models.base import Model


class WorkspaceContextProvider(ContextProvider):
    """Project-aware local workspace rooted at a single directory."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        id: str = "workspace",
        name: str = "Workspace",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        exclude_patterns: list[str] | None = None,
        max_file_lines: int = 100_000,
        max_file_length: int = 10_000_000,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.root = Path(root).expanduser().resolve() if root is not None else Path.cwd().resolve()
        self.instructions_text = instructions if instructions is not None else DEFAULT_WORKSPACE_INSTRUCTIONS
        self.exclude_patterns = exclude_patterns if exclude_patterns is not None else list(DEFAULT_EXCLUDE_PATTERNS)
        self.max_file_lines = max_file_lines
        self.max_file_length = max_file_length
        self._agent: Agent | None = None

    def status(self) -> Status:
        if not self.root.exists():
            return Status(ok=False, detail=f"root does not exist: {self.root}")
        if not self.root.is_dir():
            return Status(ok=False, detail=f"root is not a directory: {self.root}")
        return Status(ok=True, detail=str(self.root))

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_agent().run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_agent().arun(question, **kwargs))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: inspect project files under {self.root}. Use read-only "
                "`list_files`, `search_content`, and `read_file`. Paths are relative to "
                "the workspace root; common dependency, build, and agent scratch folders "
                "are excluded."
            )
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to inspect project "
            f"files under {self.root}. Common dependency, build, and agent scratch folders "
            "are excluded."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return [self._query_tool()]

    def _all_tools(self) -> list:
        return [self._build_workspace_tools()]

    # ------------------------------------------------------------------
    # Sub-agent
    # ------------------------------------------------------------------

    def _ensure_agent(self) -> Agent:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            model=self.model,
            instructions=self.instructions_text.replace("{root}", str(self.root)),
            tools=[self._build_workspace_tools()],
            markdown=True,
        )

    def _build_workspace_tools(self) -> Workspace:
        return Workspace(
            root=self.root,
            allowed=Workspace.READ_TOOLS,
            exclude_patterns=list(self.exclude_patterns),
            max_file_lines=self.max_file_lines,
            max_file_length=self.max_file_length,
        )


DEFAULT_WORKSPACE_INSTRUCTIONS = """\
You answer questions by inspecting project files under {root}.

Workflow:
1. **Map the workspace first.** Use `list_files(recursive=True)` with a
   modest `max_depth` to identify likely source, docs, and cookbook paths.
2. **Search narrowly.** Use `search_content(query, directory=...)` once you
   know the relevant subtree. Avoid whole-workspace searches unless the user
   asks for a broad audit.
3. **Read before citing.** Use `read_file(path)` or a line range for the
   files you rely on. Cite paths relative to the workspace root.
4. **Ignore generated noise.** Dependency directories, virtualenvs, build
   outputs, caches, and agent scratch folders are excluded by default.

You are read-only. No save, edit, delete, move, or shell tools are available.
If a query does not match any project file, say so plainly.
"""
