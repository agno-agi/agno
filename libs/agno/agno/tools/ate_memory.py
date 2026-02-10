"""
AteMemoryTools — Agno Toolkit integration for FoodforThought's .mv2 memory format.

Provides agent tools for storing, searching, listing, and exporting memories
via the `ate` CLI, backed by .mv2 memory files.

Usage with Agno:
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from ate_memory import AteMemoryTools

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[AteMemoryTools(memory_path="./agent-memory.mv2")],
    )
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Optional

try:
    from agno.tools import Toolkit
except ImportError:

    class Toolkit:  # type: ignore[no-redef]
        """Minimal stand-in when agno is not installed."""

        def __init__(self, **kwargs: Any) -> None:
            self.name: str = kwargs.get("name", "toolkit")
            self.instructions: str | None = kwargs.get("instructions")
            self._tools: list[Any] = kwargs.get("tools", [])

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "Use these tools to interact with a persistent .mv2 memory store.\n"
    "- `add_memory`: Save a piece of text (with optional tags and title) to long-term memory.\n"
    "- `search_memory`: Semantically search memories by query; returns the top-k results.\n"
    "- `list_memories`: Show summary information about the memory store.\n"
    "- `export_memory`: Export every memory from the store.\n"
    "- `think`: A private reasoning scratchpad — use it to work through problems "
    "step-by-step before answering. The user will NOT see these thoughts.\n"
)


class AteMemoryTools(Toolkit):
    """Agno toolkit that wraps the ``ate`` CLI for .mv2 memory operations."""

    def __init__(
        self,
        memory_path: str,
        auto_init: bool = True,
        enable_add: bool = True,
        enable_search: bool = True,
        enable_list: bool = True,
        enable_export: bool = True,
        enable_think: bool = True,
    ) -> None:
        self.memory_path: str = os.path.abspath(memory_path)
        self.auto_init: bool = auto_init
        self._initialized: bool = False

        # Verify the ate CLI is available
        if shutil.which("ate") is None:
            raise FileNotFoundError(
                "The 'ate' CLI was not found on PATH. "
                "Install it from https://github.com/FoodforThought/ate"
            )

        # Collect enabled tool methods
        tools: list[Any] = []
        if enable_add:
            tools.append(self.add_memory)
        if enable_search:
            tools.append(self.search_memory)
        if enable_list:
            tools.append(self.list_memories)
        if enable_export:
            tools.append(self.export_memory)
        if enable_think:
            tools.append(self.think)

        super().__init__(
            name="ate_memory",
            tools=tools,
            instructions=_INSTRUCTIONS,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """Create the .mv2 file if auto_init is enabled and it doesn't exist."""
        if self._initialized:
            return
        if self.auto_init and not os.path.exists(self.memory_path):
            logger.info("Auto-initializing memory file at %s", self.memory_path)
            self._run_ate(["memory", "init", "--path", self.memory_path])
        self._initialized = True

    def _run_ate(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Execute an ``ate`` CLI command and return the completed process."""
        cmd = ["ate", *args, "--format", "json"]
        logger.debug("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"ate exited with code {result.returncode}"
            logger.error("ate command failed: %s", error_msg)
            raise RuntimeError(f"ate command failed: {error_msg}")
        return result

    def _format_json(self, raw: str) -> str:
        """Try to pretty-print JSON; fall back to the raw string."""
        try:
            data = json.loads(raw)
            return json.dumps(data, indent=2)
        except (json.JSONDecodeError, TypeError):
            return raw.strip()

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    def add_memory(
        self,
        run_context: Any,
        text: str,
        tags: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        """Store a memory in the .mv2 memory file.

        Args:
            run_context: Agno RunContext (injected automatically).
            text: The memory content to store.
            tags: Optional comma-separated tags for the memory.
            title: Optional title for the memory.

        Returns:
            A confirmation message with details of the stored memory.
        """
        self._ensure_initialized()
        cmd = ["memory", "add", "--path", self.memory_path, "--text", text]
        if tags:
            cmd.extend(["--tags", tags])
        if title:
            cmd.extend(["--title", title])
        result = self._run_ate(cmd)
        return self._format_json(result.stdout)

    def search_memory(
        self,
        run_context: Any,
        query: str,
        top_k: int = 5,
    ) -> str:
        """Semantically search the .mv2 memory file.

        Args:
            run_context: Agno RunContext (injected automatically).
            query: The search query.
            top_k: Maximum number of results to return (default 5).

        Returns:
            Search results as a formatted JSON string.
        """
        self._ensure_initialized()
        cmd = [
            "memory",
            "search",
            "--path",
            self.memory_path,
            "--query",
            query,
            "--top-k",
            str(top_k),
        ]
        result = self._run_ate(cmd)
        return self._format_json(result.stdout)

    def list_memories(self, run_context: Any) -> str:
        """Return summary info about the .mv2 memory file.

        Args:
            run_context: Agno RunContext (injected automatically).

        Returns:
            Memory store information as a formatted JSON string.
        """
        self._ensure_initialized()
        cmd = ["memory", "info", "--path", self.memory_path]
        result = self._run_ate(cmd)
        return self._format_json(result.stdout)

    def export_memory(self, run_context: Any) -> str:
        """Export all memories from the .mv2 file.

        Args:
            run_context: Agno RunContext (injected automatically).

        Returns:
            All memories as a formatted JSON string.
        """
        self._ensure_initialized()
        cmd = ["memory", "export", "--path", self.memory_path]
        result = self._run_ate(cmd)
        return self._format_json(result.stdout)

    def think(self, run_context: Any, thought: str) -> str:
        """Use this tool as a private reasoning scratchpad.

        The content passed here is NOT shown to the user. Use it to
        work through complex problems step-by-step before formulating
        your final answer.

        Args:
            run_context: Agno RunContext (injected automatically).
            thought: Your internal reasoning or chain-of-thought text.

        Returns:
            An acknowledgement that the thought was recorded.
        """
        logger.debug("Think: %s", thought[:120])
        return f"Thought recorded: {thought}"
