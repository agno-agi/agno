"""Ephemeral agent spawning toolkit for Agno.

Gives an orchestrator agent the ability to create and run sub-agents
on-the-fly with fully dynamic prompts, tools, and model selection.

Inspired by Claude Code's dynamic sub-agent architecture where the
LLM itself defines the persona, instructions, and toolset for each
ephemeral agent at runtime.

Example:
    >>> from agno.agent import Agent
    >>> from agno.models.anthropic import Claude
    >>> from agno.tools.file import FileTools
    >>> from agno.tools.shell import ShellTools
    >>> from agno.tools.spawn import SpawnAgentTools
    >>>
    >>> orchestrator = Agent(
    ...     model=Claude(id="claude-sonnet-4-6"),
    ...     tools=[
    ...         FileTools(Path("."), all=True),
    ...         SpawnAgentTools(
    ...             available_tools={
    ...                 "file_read": FileTools(Path("."), enable_read_file=True),
    ...                 "shell": ShellTools(),
    ...             },
    ...             available_models={
    ...                 "fast": Claude(id="claude-haiku-4-5-20251001"),
    ...                 "balanced": Claude(id="claude-sonnet-4-6"),
    ...             },
    ...         ),
    ...     ],
    ... )
"""

import threading
from copy import deepcopy
from typing import Any, Dict, List, Optional

from agno.models.base import Model
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_warning, logger


class SpawnAgentTools(Toolkit):
    """Toolkit that lets an agent spawn ephemeral sub-agents at runtime.

    The orchestrator agent decides everything dynamically:
    - **task**: the specific prompt for the sub-agent
    - **persona**: who the sub-agent is
    - **instructions**: what the sub-agent should do and how
    - **tools_needed**: which tools to equip (from a pre-registered set)
    - **model_tier**: which model to use (from a pre-registered set)

    The sub-agent executes, returns its result, and is garbage-collected.

    Args:
        available_tools: Mapping of tool names to Toolkit or callable instances
            that sub-agents can be equipped with.
        available_models: Mapping of tier names (e.g. "fast", "balanced") to
            Model instances.
        default_model_tier: Tier used when the agent does not specify one.
        max_depth: Maximum nesting depth to prevent infinite recursion.
        inherit_session_state: Whether to pass the parent's session_state
            to the sub-agent.
    """

    def __init__(
        self,
        available_tools: Optional[Dict[str, Any]] = None,
        available_models: Optional[Dict[str, Model]] = None,
        default_model_tier: str = "balanced",
        max_depth: int = 3,
        inherit_session_state: bool = False,
        **kwargs,
    ):
        self.available_tools: Dict[str, Any] = available_tools or {}
        self.available_models: Dict[str, Model] = available_models or {}
        self.default_model_tier = default_model_tier
        self.max_depth = max_depth
        self.inherit_session_state = inherit_session_state

        # Thread-safe depth counter for nested spawns
        self._depth = threading.local()

        tools = [self.spawn_agent]
        super().__init__(name="spawn_agent_tools", tools=tools, **kwargs)

    # ------------------------------------------------------------------
    # Depth tracking helpers
    # ------------------------------------------------------------------

    @property
    def _current_depth(self) -> int:
        return getattr(self._depth, "value", 0)

    @_current_depth.setter
    def _current_depth(self, val: int) -> None:
        self._depth.value = val

    # ------------------------------------------------------------------
    # Core tool
    # ------------------------------------------------------------------

    def spawn_agent(
        self,
        task: str,
        persona: str,
        instructions: str,
        tools_needed: str = "",
        model_tier: str = "",
    ) -> str:
        """Create and run an ephemeral sub-agent for a specific task.

        The sub-agent is fully defined by YOU at call time. It executes the
        task, returns its result as text, and is immediately discarded.

        Use this when a task benefits from an isolated context or a
        specialised persona. For simple tasks, prefer your own tools.

        Args:
            task: The precise task to accomplish. Be detailed and contextual.
            persona: Who the sub-agent is (e.g. "a security auditor",
                "a Python testing expert", "a technical writer").
            instructions: Specific instructions for THIS task. Provide
                actionable, contextual guidance not generic advice.
            tools_needed: Comma-separated tool names the sub-agent needs.
                Leave empty if no tools are required.
            model_tier: Model tier to use. Leave empty for the default.

        Returns:
            str: The sub-agent's textual response.
        """
        # Guard against infinite recursion
        if self._current_depth >= self.max_depth:
            return (
                f"[ERROR] Maximum spawn depth reached ({self.max_depth}). "
                "Handle this task directly with your own tools."
            )

        # Resolve tools
        agent_tools = self._resolve_tools(tools_needed)

        # Resolve model
        model = self._resolve_model(model_tier)
        if model is None:
            return "[ERROR] No model configured for SpawnAgentTools."

        # Build instructions
        full_instructions = [
            f"You are {persona}.",
            instructions,
            "Be concise and precise. Return only what is asked for.",
        ]

        # Run the ephemeral agent
        log_debug(
            f"SpawnAgent: spawning (persona='{persona[:30]}', "
            f"model_tier='{model_tier or self.default_model_tier}', "
            f"tools=[{tools_needed}], depth={self._current_depth + 1})"
        )

        self._current_depth += 1
        try:
            return self._run_ephemeral(
                task=task,
                persona=persona,
                model=model,
                tools=agent_tools,
                instructions=full_instructions,
            )
        finally:
            self._current_depth -= 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_tools(self, tools_needed: str) -> List[Any]:
        """Resolve a comma-separated tool spec into concrete tool instances."""
        if not tools_needed or not tools_needed.strip():
            return []

        resolved: List[Any] = []
        for name in tools_needed.split(","):
            name = name.strip()
            if not name:
                continue
            if name not in self.available_tools:
                log_warning(f"SpawnAgent: unknown tool '{name}', skipping")
                continue
            tool = self.available_tools[name]
            # Deep-copy Toolkit instances to avoid shared state
            if isinstance(tool, Toolkit):
                resolved.append(deepcopy(tool))
            else:
                resolved.append(tool)
        return resolved

    def _resolve_model(self, model_tier: str) -> Optional[Model]:
        """Resolve a model tier string into a Model instance."""
        tier = model_tier.strip() if model_tier else self.default_model_tier
        model = self.available_models.get(tier)
        if model is None and tier != self.default_model_tier:
            log_warning(f"SpawnAgent: unknown tier '{tier}', falling back to '{self.default_model_tier}'")
            model = self.available_models.get(self.default_model_tier)
        return model

    def _run_ephemeral(
        self,
        task: str,
        persona: str,
        model: Model,
        tools: List[Any],
        instructions: List[str],
    ) -> str:
        """Instantiate an ephemeral Agent, run the task, and return the result."""
        # Import here to avoid circular imports at module level
        from agno.agent.agent import Agent

        try:
            ephemeral = Agent(
                name=f"spawn-{persona[:20].replace(' ', '-')}",
                model=model,
                tools=tools if tools else None,
                instructions=instructions,
                markdown=True,
                # Ephemeral: no database, no memory, no session persistence
            )
            result = ephemeral.run(task)
            return result.content or "[The sub-agent returned no content]"
        except Exception as e:
            logger.warning(f"SpawnAgent: ephemeral agent failed: {e}")
            return f"[ERROR] Ephemeral agent failed: {e}"
