"""Dynamic subagent support for Agent and Team.

This module provides two public symbols:

* ``SubAgentConfig`` — spawn-time *policy* (tool delegation, model tiers,
  concurrency).  It intentionally does **not** duplicate Agent configuration
  fields; use ``Agent.subagent_template`` for that.

* ``SubAgentToolkit`` — registers ``spawn_agent`` (sync) and ``aspawn_agent``
  (async) as tools on the parent Agent or Team.

Isolation guarantee
-------------------
A spawned subagent runs with its own fresh ``run_messages`` list.  Every tool
call it makes — including large database queries, file reads, or API dumps —
stays inside that isolated context.  The parent only receives the subagent's
final text answer, keeping the parent's context window clean and cost-efficient.

This is architecturally different from ``CompressionManager``, which compresses
tool results that are *already in* the context after the fact.  Subagent
isolation prevents them from entering the parent's context in the first place.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.team.team import Team


class SubAgentConfig(BaseModel):
    """Spawn-time policy for dynamically created subagents.

    Controls **how** subagents are spawned — tool delegation rules, model-tier
    selection, concurrency limits — not **what** they look like.  Configure the
    subagent's model, knowledge base, tools, and any other capability via
    ``Agent.subagent_template``.

    .. note::
        Spawned subagents are always ephemeral: ``db``, ``stream``,
        ``telemetry``, ``num_history_runs``, and ``enable_dynamic_subagents``
        are forced to ephemeral defaults (``None``/``False``/``0``) regardless
        of what the ``subagent_template`` specifies. Set these fields on the
        parent agent instead. Overrides are logged at debug level.

    Example::

        from agno.agent import Agent, SubAgentConfig
        from agno.models.openai import OpenAIChat

        template = Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            markdown=True,
        )

        agent = Agent(
            name="orchestrator",
            enable_dynamic_subagents=True,
            subagent_template=template,
            subagent_config=SubAgentConfig(
                context_heavy_tools=["query_db", "read_file"],
                model_tiers={"fast": "gpt-4o-mini", "standard": "gpt-4o"},
                allow_model_tier_selection=True,
                max_concurrent=3,
            ),
        )
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    # ── Tool delegation ──────────────────────────────────────────────────────
    inherit_parent_tools: bool = False
    """Give every spawned subagent *all* tools the parent has."""

    allowed_tools: Optional[List[str]] = None
    """Whitelist of tool names permitted on spawned subagents.

    Applied to **both** template tools and parent tools:

    * When ``None`` (default), no whitelist — template tools pass through
      unchanged and the LLM may delegate any parent tool (subject to
      ``allow_tool_selection``).
    * When set, the whitelist is enforced globally. Toolkits on the template
      or parent contribute only the specific ``Function`` objects whose names
      appear in the whitelist — the entire toolkit is never delegated.

    Set to ``[]`` to expose zero tools to any subagent.
    """

    allow_tool_selection: bool = True
    """Let the LLM choose which tools to give each subagent at spawn time."""

    context_heavy_tools: Optional[List[str]] = None
    """Tool names that return large outputs (DB queries, file reads, web pages).
    These are injected into the parent's guidance as 'always route via spawn_agent'."""

    # ── Model tier selection ─────────────────────────────────────────────────
    model_tiers: Optional[Dict[str, str]] = None
    """Map of tier label → model ID string.

    Example::

        model_tiers={
            "fast":     "gpt-4o-mini",
            "standard": "gpt-4o",
            "powerful": "o3",
        }
    """

    allow_model_tier_selection: bool = False
    """Expose ``model_tier`` parameter in ``spawn_agent`` so the LLM can pick
    a cost-appropriate model for each task."""

    tier_hints: Optional[Dict[str, str]] = None
    """Optional mapping of tier label → usage hint shown to the LLM in guidance.
    Merged with built-in defaults (``fast``, ``standard``, ``powerful``).

    Example::

        tier_hints={
            "cheap": "simple lookups, keyword extraction",
            "turbo": "high-speed summarisation",
        }
    """

    # ── Context injection ────────────────────────────────────────────────────
    inject_session_state: bool = False
    """Embed parent ``session_state`` as read-only JSON in the subagent's
    ``additional_context``.  The subagent sees the state but cannot write back."""

    # ── Concurrency ──────────────────────────────────────────────────────────
    max_concurrent: int = Field(default=5, ge=1)
    """Maximum number of subagents running simultaneously (must be >= 1).
    Enforced via a ``threading.Semaphore`` (sync) and ``asyncio.Semaphore`` (async)."""

    # ── Observability ─────────────────────────────────────────────────────────
    log_subagent_runs: bool = True
    """Emit ``log_info`` when a subagent is spawned and when it completes.
    Each line includes role, truncated task, spawn depth, token counts, and
    elapsed time.  Set to ``False`` to suppress all lifecycle logs."""

    show_subagent_output: bool = False
    """Print the subagent's full response to stdout after it completes.
    Useful during development and debugging.  Suppressed by default."""


class SubAgentToolkit(Toolkit):
    """Registers ``spawn_agent`` and ``aspawn_agent`` as tools on a parent Agent or Team.

    The spawned subagent is built by deep-copying ``parent.subagent_template``
    (if set) and overriding only the per-spawn fields (name, instructions,
    tools, model, metadata).  If no template is provided a minimal default
    Agent is used with the parent's model.

    Context isolation is architectural: the subagent executes inside its own
    fresh ``run_messages`` list, so intermediate tool outputs never appear in
    the parent's context window.
    """

    def __init__(self, parent: Union["Agent", "Team"], config: SubAgentConfig) -> None:
        self._parent = parent
        self._config = config
        # Semaphores are created lazily to respect event-loop lifecycle for async
        self._sync_semaphore = threading.Semaphore(config.max_concurrent)
        self._async_semaphore: Optional[asyncio.Semaphore] = None
        self._async_semaphore_lock: asyncio.Lock = asyncio.Lock()

        super().__init__(
            name="subagent",
            tools=[self.spawn_agent],
            async_tools=[(self.aspawn_agent, "spawn_agent")],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Public tools — called by the LLM
    # ──────────────────────────────────────────────────────────────────────────

    def spawn_agent(
        self,
        role: str,
        instructions: str,
        task: str,
        tools: Optional[List[str]] = None,
        expected_output: Optional[str] = None,
        model_tier: Optional[str] = None,
    ) -> str:
        """Spawn an isolated subagent, run it synchronously, and return its answer.

        The subagent executes in a completely fresh context.  Every tool call it
        makes stays inside that isolated context — nothing leaks back into this
        agent's message history, keeping your context window focused.

        Args:
            role: Name / persona for the subagent (e.g. ``"sql_analyst"``).
            instructions: System-level instructions the subagent should follow.
            task: The concrete task for the subagent to complete.
            tools: Optional list of parent-tool names to give this subagent.
                   Filtered against ``SubAgentConfig.allowed_tools`` whitelist.
            expected_output: Optional description of the desired output format.
            model_tier: Optional tier name (e.g. ``"fast"``, ``"standard"``,
                        ``"powerful"``) as defined in ``SubAgentConfig.model_tiers``.
                        Has no effect unless ``SubAgentConfig.allow_model_tier_selection=True``
                        and the tier name exists in ``SubAgentConfig.model_tiers``; otherwise
                        the template model is used and this parameter is silently ignored.

        Returns:
            The string content returned by the subagent, or a fallback message.

        .. warning::
            This method runs the subagent synchronously and holds the semaphore
            for the full execution duration.  **Do NOT call it from an async
            context** (e.g. a FastAPI request handler or an async Jupyter cell)
            as it will block the event loop.  Use ``aspawn_agent`` instead when
            running inside an async application.
        """
        spawn_depth = (getattr(self._parent, "metadata", None) or {}).get("spawn_depth", 0) + 1
        with self._sync_semaphore:
            t0 = time.monotonic()
            if self._config.log_subagent_runs:
                log_info(f"Spawning subagent '{role}' | task={task[:80]!r} | depth={spawn_depth}")
            subagent = self._build_subagent(role, instructions, tools, expected_output, model_tier, task)
            try:
                result = subagent.run(input=task, stream=False)
            except Exception as e:
                log_warning(f"Subagent '{role}' failed: {e}")
                return f"Subagent '{role}' failed: {e}"
            if self._config.log_subagent_runs:
                duration = time.monotonic() - t0
                m = result.metrics if result else None
                token_str = (
                    f" | tokens={m.total_tokens} (in={m.input_tokens} out={m.output_tokens})"
                    if m and m.total_tokens
                    else ""
                )
                log_info(f"Subagent '{role}' completed{token_str} | duration={duration:.2f}s | depth={spawn_depth}")
            if self._config.show_subagent_output and result and result.content:
                print(f"\n--- Subagent: {role} ---")
                print(result.content)
                print(f"--- End Subagent: {role} ---\n")
        if result and result.content:
            return str(result.content)
        return "Subagent completed with no output."

    async def aspawn_agent(
        self,
        role: str,
        instructions: str,
        task: str,
        tools: Optional[List[str]] = None,
        expected_output: Optional[str] = None,
        model_tier: Optional[str] = None,
    ) -> str:
        """Async version of ``spawn_agent``.

        Args:
            role: Name / persona for the subagent.
            instructions: System-level instructions the subagent should follow.
            task: The concrete task for the subagent to complete.
            tools: Optional list of parent-tool names to give this subagent.
            expected_output: Optional description of the desired output format.
            model_tier: Optional tier name as defined in ``SubAgentConfig.model_tiers``.
                        Has no effect unless ``SubAgentConfig.allow_model_tier_selection=True``
                        and the tier name exists in ``SubAgentConfig.model_tiers``; otherwise
                        the template model is used and this parameter is silently ignored.

        Returns:
            The string content returned by the subagent, or a fallback message.
        """
        spawn_depth = (getattr(self._parent, "metadata", None) or {}).get("spawn_depth", 0) + 1
        async with await self._get_async_semaphore():
            t0 = time.monotonic()
            if self._config.log_subagent_runs:
                log_info(f"Spawning subagent '{role}' | task={task[:80]!r} | depth={spawn_depth}")
            subagent = self._build_subagent(role, instructions, tools, expected_output, model_tier, task)
            try:
                result = await subagent.arun(input=task, stream=False)
            except Exception as e:
                log_warning(f"Subagent '{role}' failed: {e}")
                return f"Subagent '{role}' failed: {e}"
            if self._config.log_subagent_runs:
                duration = time.monotonic() - t0
                m = result.metrics if result else None
                token_str = (
                    f" | tokens={m.total_tokens} (in={m.input_tokens} out={m.output_tokens})"
                    if m and m.total_tokens
                    else ""
                )
                log_info(f"Subagent '{role}' completed{token_str} | duration={duration:.2f}s | depth={spawn_depth}")
            if self._config.show_subagent_output and result and result.content:
                print(f"\n--- Subagent: {role} ---")
                print(result.content)
                print(f"--- End Subagent: {role} ---\n")
        if result and result.content:
            return str(result.content)
        return "Subagent completed with no output."

    # ──────────────────────────────────────────────────────────────────────────
    # Guidance — injected into parent's system prompt at initialisation
    # ──────────────────────────────────────────────────────────────────────────

    def build_guidance(self) -> str:
        """Return the context-isolation guidance block for the parent's system prompt.

        This is called once by :func:`set_dynamic_subagents` /
        :func:`_set_dynamic_subagents` during agent/team initialisation and
        appended to the parent's instructions.

        .. warning::
            The returned string is a **snapshot** of ``SubAgentConfig`` at
            initialisation time. Mutating ``subagent_config`` after
            ``initialize_agent()`` / ``initialize_team()`` (e.g. adding a
            new ``context_heavy_tool``) will **not** update the guidance —
            the LLM will continue to see the original text. Reconfigure
            before initialisation, or rebuild the agent if you need to
            change this at runtime.
        """
        lines = [
            "--- Dynamic Subagent Guidance ---",
            "You have a spawn_agent tool that creates isolated specialist subagents.",
            "Subagent tool outputs stay inside the subagent's own context — they",
            "never appear in your message history, keeping your context clean.",
            "",
            "USE spawn_agent when:",
            "  - A tool returns large data (DB queries, file reads, API responses)",
            "  - A subtask is self-contained: you only need the final answer",
            "  - You want to avoid polluting your context with intermediate results",
            "",
            "DO NOT use spawn_agent when:",
            "  - You need the raw output (not a summary) for your own reasoning",
            "  - The task requires interactive back-and-forth with the user",
            "  - It is a single, small tool call with minimal output",
        ]

        if self._config.context_heavy_tools:
            lines += [
                "",
                "ALWAYS route these tools through spawn_agent (they produce large outputs):",
            ]
            for name in self._config.context_heavy_tools:
                lines.append(f"  - {name}")

        if self._config.allow_model_tier_selection and self._config.model_tiers:
            lines += [
                "",
                "Model tier selection — use the model_tier parameter to reduce cost:",
            ]
            _default_hints: Dict[str, str] = {
                "fast": "extraction, formatting, simple classification",
                "standard": "summarisation, code generation, analysis",
                "powerful": "complex multi-step reasoning, research synthesis",
            }
            _hints = {**_default_hints, **(self._config.tier_hints or {})}
            for tier, model_id in self._config.model_tiers.items():
                hint = _hints.get(tier, "")
                suffix = f"  (best for: {hint})" if hint else ""
                lines.append(f"  - '{tier}' → {model_id}{suffix}")

        lines.append("--- End Subagent Guidance ---")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_subagent_toolkits(tools: Optional[List[Any]]) -> Optional[List[Any]]:
        """Return ``tools`` with any ``SubAgentToolkit`` instances removed.

        Invariant: a spawned subagent must never carry a ``SubAgentToolkit``
        in its tools, otherwise ``spawn_agent`` would be reachable despite
        ``enable_dynamic_subagents=False`` on the subagent.

        Returns ``None`` if the input is ``None`` so callers can distinguish
        "no tools configured" from "tools explicitly empty after filtering".
        """
        if tools is None:
            return None
        return [t for t in tools if not isinstance(t, SubAgentToolkit)]

    async def _get_async_semaphore(self) -> asyncio.Semaphore:
        """Lazily create the async semaphore inside the running event loop.

        Uses double-checked locking to be safe when multiple coroutines
        enter aspawn_agent concurrently before the semaphore is initialized.
        """
        if self._async_semaphore is None:
            async with self._async_semaphore_lock:
                if self._async_semaphore is None:
                    self._async_semaphore = asyncio.Semaphore(self._config.max_concurrent)
        return self._async_semaphore

    def _build_subagent(
        self,
        role: str,
        instructions: str,
        tool_names: Optional[List[str]],
        expected_output: Optional[str],
        model_tier: Optional[str],
        task: str,
    ) -> "Agent":
        """Create an ephemeral Agent for a single spawn."""
        from agno.agent.agent import Agent
        from agno.team.team import Team

        # ── Resolve template ──────────────────────────────────────────────────
        template: Optional[Agent] = getattr(self._parent, "subagent_template", None)
        if template is None:
            # Minimal default: inherit parent's model so the subagent can run.
            # NOTE: this Agent is intentionally not yet initialized — Agent.run()
            # and Agent.arun() call initialize_agent() lazily on first invocation,
            # so it is safe to deep_copy and pass to run() without calling
            # initialize_agent() here.
            parent_model = getattr(self._parent, "model", None)
            template = Agent(model=parent_model)

        # ── Per-spawn overrides ───────────────────────────────────────────────
        model = self._resolve_model(model_tier, template)
        # Invariant: a spawned subagent must NEVER carry a SubAgentToolkit in
        # its tools, regardless of how the template was configured. A template
        # that was itself initialized with enable_dynamic_subagents=True will
        # have a SubAgentToolkit wired into its .tools; deep-copying it would
        # leak spawn_agent back to the child and bypass the recursion guard.
        template_tools_raw = getattr(template, "tools", None)
        template_tools_sanitized = self._strip_subagent_toolkits(template_tools_raw)
        template_leaked_toolkit = template_tools_raw is not None and (
            len(template_tools_sanitized or []) != len(template_tools_raw)
        )
        resolved_tools = self._resolve_tools(tool_names, template_tools_sanitized)
        additional_context = self._build_additional_context()

        # ── Lineage metadata ──────────────────────────────────────────────────
        parent_id = getattr(self._parent, "id", None)
        parent_name = getattr(self._parent, "name", None)
        spawn_depth: int = (getattr(self._parent, "metadata", None) or {}).get("spawn_depth", 0) + 1
        team_id = parent_id if isinstance(self._parent, Team) else None

        log_debug(f"Spawning subagent | parent={parent_name}({parent_id}) role={role!r} depth={spawn_depth}")

        # ── Build via deep_copy — preserves all template config ───────────────
        # NOTE: team_id is intentionally excluded from the update dict.
        # It is a dataclass field on Agent but NOT a parameter in Agent.__init__,
        # so passing it via deep_copy(update={...}) would raise TypeError.
        # It is set directly on the subagent after construction instead.
        update: dict = {
            "name": role,
            "description": f"Ephemeral subagent: {role}",
            "instructions": instructions,
            "expected_output": expected_output,
            "model": model,
            # Ephemeral: no persistence, no telemetry, no history bleed
            "db": None,
            "stream": False,
            "telemetry": False,
            "num_history_runs": 0,
            # Subagent should not spawn further subagents (prevents recursion)
            "enable_dynamic_subagents": False,
            # Lineage
            "metadata": {
                "spawned_by_agent_id": parent_id,
                "spawned_by_agent_name": parent_name,
                "spawn_role": role,
                "spawn_task": task[:200],
                "spawn_depth": spawn_depth,
            },
        }
        # Log which template fields we are clobbering with ephemeral defaults.
        # These are intentional — subagents are meant to be stateless, non-telemetered,
        # single-run workers — but users should see it in debug logs.
        _ephemeral_defaults = {
            "db": None,
            "stream": False,
            "telemetry": False,
            "num_history_runs": 0,
            "enable_dynamic_subagents": False,
        }
        for _field, _ephemeral_value in _ephemeral_defaults.items():
            _template_value = getattr(template, _field, None)
            if _template_value is not None and _template_value != _ephemeral_value:
                log_debug(
                    f"Subagent '{role}': overriding template field '{_field}' "
                    f"({_template_value!r} -> {_ephemeral_value!r}) "
                    f"because subagents are ephemeral."
                )
        # Override tools when we have an explicit resolution, OR when the
        # template carried a SubAgentToolkit that we had to strip. Without the
        # second branch, deep_copy would copy the original (unsanitised) tools
        # list and re-attach the toolkit to the subagent.
        if resolved_tools is not None:
            update["tools"] = resolved_tools
        elif template_leaked_toolkit:
            update["tools"] = template_tools_sanitized
        # Only override additional_context when we actually have a value.
        # Passing None in the update dict would clobber the template's own
        # additional_context field during deep_copy.
        if additional_context is not None:
            update["additional_context"] = additional_context
        subagent = template.deep_copy(update=update)
        # Set team_id after construction — it is a dataclass field that is
        # assigned externally, not accepted by Agent.__init__.
        if team_id is not None:
            subagent.team_id = team_id
        return subagent

    def _resolve_model(self, model_tier: Optional[str], template: "Agent") -> Any:
        """Resolve the model for the spawned subagent.

        Priority:
        1. ``model_tier`` → looked up in ``config.model_tiers`` via ``get_model()``
        2. Template model
        3. Parent model
        """
        if (
            model_tier
            and self._config.allow_model_tier_selection
            and self._config.model_tiers
            and model_tier in self._config.model_tiers
        ):
            try:
                from agno.models.utils import get_model

                resolved = get_model(self._config.model_tiers[model_tier])
                if resolved is not None:
                    return resolved
            except Exception:
                log_warning(
                    f"Could not resolve model tier '{model_tier}' "
                    f"('{self._config.model_tiers.get(model_tier)}'). "
                    "Falling back to template model."
                )
        # Fall through: template model → parent model
        return getattr(template, "model", None) or getattr(self._parent, "model", None)

    @staticmethod
    def _filter_tools_by_names(tools: Optional[List[Any]], permitted: set) -> List[Any]:
        """Filter a tools list down to entries whose name is in ``permitted``.

        * ``Toolkit`` → contributes each individually permitted ``Function``.
        * ``Function`` → kept if ``tool.name`` is in ``permitted``.
        * Plain callable → kept if ``__name__`` is in ``permitted``.
        * ``SubAgentToolkit`` is always excluded (defence in depth).
        """
        from agno.tools import Toolkit as _Toolkit
        from agno.tools.function import Function as _Function

        result: List[Any] = []
        for tool in tools or []:
            if isinstance(tool, SubAgentToolkit):
                continue
            if isinstance(tool, _Toolkit):
                for fn_name, fn_obj in tool.functions.items():
                    if fn_name in permitted:
                        result.append(fn_obj)
            elif isinstance(tool, _Function):
                if tool.name in permitted:
                    result.append(tool)
            elif callable(tool):
                name = getattr(tool, "__name__", None)
                if name and name in permitted:
                    result.append(tool)
        return result

    def _resolve_tools(
        self,
        tool_names: Optional[List[str]],
        template_tools: Optional[List[Any]],
    ) -> Optional[List[Any]]:
        """Build the tool list for the spawned subagent.

        Priority / composition:
        1. ``inherit_parent_tools=True`` → return parent's full tool list minus any
           ``SubAgentToolkit`` instances (prevents recursive spawning).
        2. Start from template's own tools as the base. If ``allowed_tools`` is
           set, the template tools are filtered function-by-function against
           that whitelist too — not just parent tools. This prevents the
           whitelist from being silently bypassed when the template carries a
           toolkit.
        3. ``allow_tool_selection=True`` + ``tool_names`` → append matching
           parent tools (filtered against ``allowed_tools`` whitelist,
           ``SubAgentToolkit`` excluded).
        """
        if self._config.inherit_parent_tools:
            parent_tools_raw = getattr(self._parent, "tools", None)
            if parent_tools_raw is None:
                # Parent has no tools at all — return None so the caller falls back
                # to the template's tools (nothing to inherit and nothing to strip).
                return None
            # Filter out SubAgentToolkit — a spawned subagent must never be able
            # to spawn further subagents even if inherit_parent_tools=True.
            # Return the filtered list as-is (even if empty) rather than collapsing
            # to None. An empty list means "explicit override: no tools" — collapsing
            # to None would fall back to the template's tools, which could re-leak
            # tools the caller explicitly filtered out.
            return self._strip_subagent_toolkits(parent_tools_raw)

        # Use `is not None` rather than truthiness so that allowed_tools=[]
        # correctly means "empty whitelist, block everything" instead of being
        # treated as the "no whitelist" sentinel (allowed_tools=None).
        allowed = set(self._config.allowed_tools) if self._config.allowed_tools is not None else None

        # Base: template tools, whitelist-filtered when a whitelist is set.
        # When no whitelist is configured the template tools pass through
        # unchanged. When a whitelist IS set, it applies to every tool source
        # — template included — otherwise users who configured both a
        # subagent_template (with a toolkit) and an allowed_tools list would
        # have the whitelist silently bypassed by the template toolkit.
        if allowed is not None:
            result: List[Any] = self._filter_tools_by_names(template_tools, allowed)
        else:
            result = list(template_tools or [])

        if not tool_names or not self._config.allow_tool_selection:
            return result or None

        parent_tools_raw = getattr(self._parent, "tools", None) or []
        requested = set(tool_names)
        permitted = (allowed & requested) if allowed is not None else requested

        result.extend(self._filter_tools_by_names(parent_tools_raw, permitted))

        return result or None

    def _build_additional_context(self) -> Optional[str]:
        """Build ``additional_context`` for the subagent (session-state injection only).

        The state is embedded as read-only JSON — the subagent cannot write back
        to the parent's session.  We intentionally do *not* pass it as the live
        ``session_state`` argument to ``run()`` to avoid unintentional mutation.

        Falls back to ``repr()`` (capped at 4KB) if the state contains circular
        references or other structures ``json.dumps`` cannot handle.
        """
        if not self._config.inject_session_state:
            return None
        state = getattr(self._parent, "session_state", None)
        if not state:
            return None

        _warned = False

        def _default_serializer(obj: object) -> str:
            nonlocal _warned
            if not _warned:
                log_warning(
                    f"session_state contains non-serializable value(s); "
                    f"they will be converted to strings. "
                    f"First non-serializable type: {type(obj).__name__}"
                )
                _warned = True
            return str(obj)

        try:
            serialized = json.dumps(state, indent=2, default=_default_serializer)
        except (ValueError, TypeError) as e:
            log_warning(
                f"session_state could not be JSON-serialized "
                f"({e.__class__.__name__}: {e}); falling back to repr(). "
                f"Check for circular references or unsupported types."
            )
            serialized = repr(state)[:4000]

        return "Parent session state (read-only):\n" + serialized
