"""
Session recall tools for searching and browsing run history.

Provides tools to search conversation content, find tool usage,
and browse compaction checkpoints. Requires a PostgreSQL backend.
"""

from textwrap import dedent
from typing import Any, List, Optional, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_error


class SessionRecallTools(Toolkit):
    """Tools for searching and browsing session history.

    These tools help agents recall what happened earlier:
    - Search conversation content (input/output)
    - Find runs that used specific tools
    - Browse compaction checkpoints (compression events)
    - Search compaction summaries

    Requires PostgresDb for JSONB search capabilities.
    """

    DEFAULT_INSTRUCTIONS = dedent("""\
        You have session recall tools to search your conversation history:

        - `search_content`: Search what was said (input/output text)
        - `find_tool_usage`: Find runs where a specific tool was used
        - `get_checkpoints`: See compaction events (context compression points)
        - `search_summaries`: Search compacted summaries

        Use these when you need to recall specific details from earlier
        in the conversation, especially after context compression.
        """)

    def __init__(
        self,
        db: Union[BaseDb, AsyncBaseDb],
        enable_search_content: bool = True,
        enable_find_tool: bool = True,
        enable_checkpoints: bool = True,
        enable_search_summaries: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """Initialize SessionRecallTools.

        Args:
            db: Database backend (PostgresDb required for full functionality)
            enable_search_content: Enable search_content tool
            enable_find_tool: Enable find_tool_usage tool
            enable_checkpoints: Enable get_checkpoints tool
            enable_search_summaries: Enable search_summaries tool
            instructions: Custom instructions (overrides default)
            add_instructions: Whether to add instructions to system prompt
        """
        self.instructions = instructions or self.DEFAULT_INSTRUCTIONS
        self.db = db

        tools: List[Any] = []
        if enable_search_content:
            tools.append(self.search_content)
        if enable_find_tool:
            tools.append(self.find_tool_usage)
        if enable_checkpoints:
            tools.append(self.get_checkpoints)
        if enable_search_summaries:
            tools.append(self.search_summaries)

        super().__init__(
            name="session_recall_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    def search_content(
        self,
        run_context: RunContext,
        query: str,
        limit: int = 5,
    ) -> str:
        """Search conversation content for a term.

        Searches both user input and agent output text.

        Args:
            query: What to search for
            limit: Maximum results to return
        """
        try:
            session_id = run_context.session_id
            if not session_id:
                return "No session context available."

            if not hasattr(self.db, "search_runs_by_content"):
                return "Content search requires PostgresDb."

            results = self.db.search_runs_by_content(
                query=query,
                session_id=session_id,
                limit=limit,
            )

            if not results:
                return f"No matches found for '{query}' in conversation history."

            lines = [f"Found {len(results)} run(s) matching '{query}':\n"]
            for r in results:
                run_id = r.get("run_id", "")[:8]
                input_preview = r.get("input_preview", "")
                content_preview = r.get("content_preview", "")

                lines.append(f"Run {run_id}:")
                if input_preview and query.lower() in input_preview.lower():
                    lines.append(f"  Input: ...{self._highlight_match(input_preview, query)}...")
                if content_preview and query.lower() in content_preview.lower():
                    lines.append(f"  Output: ...{self._highlight_match(content_preview, query)}...")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            log_error(f"Error searching content: {e}")
            return f"Error: {e}"

    def find_tool_usage(
        self,
        run_context: RunContext,
        tool_name: str,
        limit: int = 5,
    ) -> str:
        """Find runs where a specific tool was used.

        Use this to trace when and how a tool was called.

        Args:
            tool_name: Name of the tool to find (e.g., "read_file", "search")
            limit: Maximum results to return
        """
        try:
            session_id = run_context.session_id
            if not session_id:
                return "No session context available."

            if not hasattr(self.db, "find_runs_by_tool"):
                return "Tool search requires PostgresDb."

            results = self.db.find_runs_by_tool(
                tool_name=tool_name,
                session_id=session_id,
                limit=limit,
            )

            if not results:
                return f"No runs found using tool '{tool_name}'."

            lines = [f"Found {len(results)} run(s) using '{tool_name}':\n"]
            for r in results:
                run_id = r.get("run_id", "")[:8]
                matching = r.get("matching_tools", [])

                lines.append(f"Run {run_id}: {len(matching)} call(s)")
                for t in matching[:3]:
                    args = t.get("tool_args", {})
                    args_preview = str(args)[:100] if args else ""
                    lines.append(f"  - {args_preview}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            log_error(f"Error finding tool usage: {e}")
            return f"Error: {e}"

    def get_checkpoints(
        self,
        run_context: RunContext,
        limit: int = 5,
    ) -> str:
        """Get compaction checkpoints (context compression events).

        Shows when context was compressed and what summaries were created.
        Use this to understand the history of context compression.

        Args:
            limit: Maximum checkpoints to return
        """
        try:
            session_id = run_context.session_id
            if not session_id:
                return "No session context available."

            if not hasattr(self.db, "get_compaction_checkpoints"):
                return "Checkpoint retrieval requires PostgresDb."

            results = self.db.get_compaction_checkpoints(
                session_id=session_id,
                limit=limit,
            )

            if not results:
                return (
                    "No compaction checkpoints found.\n"
                    "Context hasn't been compressed yet - all messages are in your visible context."
                )

            lines = [f"Found {len(results)} compaction checkpoint(s):\n"]
            for r in results:
                run_id = r.get("run_id", "")[:8]
                summary = r.get("summary", "")
                compacted = r.get("compacted_count", 0)
                total = r.get("total_compactions", 0)
                saved = r.get("tokens_saved", 0)

                lines.append(f"Checkpoint at run {run_id}:")
                lines.append(f"  Compaction #{total}: {compacted} messages, {saved} tokens saved")
                if summary:
                    preview = summary[:300] + "..." if len(summary) > 300 else summary
                    lines.append(f"  Summary: {preview}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            log_error(f"Error getting checkpoints: {e}")
            return f"Error: {e}"

    def search_summaries(
        self,
        run_context: RunContext,
        query: str,
        limit: int = 5,
    ) -> str:
        """Search compaction summaries for a topic.

        Only searches content that has been compressed. If no results,
        try search_content for non-compressed history.

        Args:
            query: What to search for
            limit: Maximum results to return
        """
        try:
            session_id = run_context.session_id
            if not session_id:
                return "No session context available."

            if not hasattr(self.db, "search_runs_by_summary"):
                return "Summary search requires PostgresDb."

            results = self.db.search_runs_by_summary(
                query=query,
                session_id=session_id,
                limit=limit,
            )

            if not results:
                return (
                    f"No matches for '{query}' in compaction summaries.\n"
                    "Try search_content to search non-compressed history."
                )

            lines = [f"Found {len(results)} summary match(es) for '{query}':\n"]
            for r in results:
                run_id = r.get("run_id", "")[:8]
                summary = r.get("compaction_summary", "")
                if summary:
                    preview = summary[:300] + "..." if len(summary) > 300 else summary
                    lines.append(f"Run {run_id}:")
                    lines.append(f"  {preview}\n")

            return "\n".join(lines)

        except Exception as e:
            log_error(f"Error searching summaries: {e}")
            return f"Error: {e}"

    def _highlight_match(self, text: str, query: str, context: int = 50) -> str:
        """Extract context around the match."""
        lower_text = text.lower()
        lower_query = query.lower()
        idx = lower_text.find(lower_query)
        if idx == -1:
            return text[: context * 2]

        start = max(0, idx - context)
        end = min(len(text), idx + len(query) + context)
        return text[start:end]
