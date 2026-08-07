"""Subagents: let an agent spin up restricted copies of itself to get tasks done in parallel.

Enable subagents with Agent(subagents=True), or pass Agent(subagents=SubagentsManager(...))
to control the options. At run time the agent gets a spawn_agent tool built as a per-run
closure (the same mechanism Teams use for delegate_task_to_member). The model selects the
subagent's model and tools per spawn from the allowed options declared on the manager.

Subagents run in-process inside the parent's run and session: their events stream
nested into the parent's run (tagged with parent_run_id) and the tool result is the
subagent's answer. Subagent runs are ephemeral - they are never persisted.
"""

from __future__ import annotations

import asyncio
import threading
import time
from copy import copy
from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union
from uuid import uuid4

from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.run.agent import (
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunOutput,
    RunOutputEvent,
    RunStatus,
)
from agno.run.base import RunContext
from agno.run.cancel import (
    acancel_run,
    araise_if_cancelled,
    aregister_member_run,
    cancel_run,
    raise_if_cancelled,
    register_member_run,
)
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error
from agno.utils.merge_dict import merge_dictionaries

if TYPE_CHECKING:
    from agno.agent.agent import Agent

# Terminal events emitted by a subagent; forwarded even when draining after a cancel.
_TERMINAL_EVENT_TYPES = (RunCancelledEvent, RunCompletedEvent, RunErrorEvent)

DEFAULT_INSTRUCTIONS = dedent("""\
    You can delegate tasks to subagents: isolated copies of yourself with a fresh
    context that work on a task inside this run and return the result. Use them to
    parallelize independent work and to keep noisy side-work out of this conversation.
    - Call spawn_agent once per independent sub-task. Call it multiple times in the
      same response to run subagents in parallel; total time equals the largest task,
      not the sum.
    - Only spawn when it pays off: several independent pieces, or one large
      self-contained chunk of research or grunt work. Do small tasks, follow-up
      questions and sequential work (where each step needs the previous step's
      result) yourself - spawning costs more than doing it.
    - Keep each task small and atomic: one topic, component, or question per subagent.
      Never give one subagent a numbered list of independent items - split the list
      into one spawn_agent call per item. Never give two subagents overlapping work.
    - Pick the model option best suited to each task, and optionally restrict the
      subagent to the tools it needs (see the spawn_agent tool description for the
      allowed options).
    - Subagents start fresh and do not see this conversation. Every brief must be
      self-contained - full context, precise scope, and the exact output to return
      (a summary, a list of findings with sources - never raw dumps).
    - Keep the hardest parts of the work for yourself and combine the subagent results
      into your final answer.""")

_SPAWN_DESCRIPTION = dedent("""\
    Delegate a task to a subagent and return its result. The subagent starts fresh
    and does not see this conversation, so every task must be self-contained. Pick
    the model option best suited to the task, and optionally restrict the subagent
    to a subset of the allowed tools.""")


def _merge_state(run_context: RunContext, state_copy: Optional[Dict[str, Any]]) -> None:
    """Merge the subagent's session-state changes back into the parent's state.

    The subagent runs on a copy of the parent's session_state (Teams member pattern);
    whatever it changed is merged back once the spawn finishes, so state updates made
    by subagents are not silently lost.
    """
    if run_context.session_state is not None and state_copy is not None:
        merge_dictionaries(run_context.session_state, state_copy)


def _final_result(child_output: Optional[RunOutput], streamed_content: bool) -> Iterator[str]:
    """Yield the tool-result string when the streamed events did not carry one.

    In streaming mode the tool result is assembled from the subagent's content-delta
    events, so this only fills the gaps: the run ended in error, paused for human
    input (unsupported in subagents), or produced no streamed content at all.
    """
    if child_output is not None and child_output.status == RunStatus.error:
        error_content = child_output.get_content_as_string()
        yield "Subagent task failed: " + (error_content or "the run ended with an error")
        return
    if child_output is not None and child_output.is_paused:
        yield "Subagent task paused waiting for human input, which subagents do not support."
        return
    if streamed_content:
        return
    content = child_output.get_content_as_string() if child_output is not None else ""
    yield content if content else "The subagent returned no output."


@dataclass
class SubagentsManager:
    """Configuration and spawn machinery for subagents.

    Attach to an agent via Agent(subagents=SubagentsManager(...)) or enable the
    defaults with Agent(subagents=True). The agent then gets a spawn_agent tool
    whose model and tools the model picks per spawn from the allowed options
    declared here.

    Subagents run in-process in the parent's run and session. Their events stream
    nested into the parent's run (tagged with parent_run_id) so they render as
    sub-agent activity in the AgentOS UI, and the tool result is the subagent's
    answer. Subagent runs are ephemeral: they are never written to the database.

    Args:
        model: Single model every subagent runs on. Mutually exclusive with models.
        models: Named model options the model can pick from per spawn. Values are
            a Model or a (Model, "when to use it") tuple - the description is shown
            next to the option name in the spawn_agent tool description, e.g.
            {"fast": luna, "deep": (terra, "complex analysis and synthesis")}.
            The first entry is the default. When neither model nor models is set,
            subagents run on the parent agent's model.
        tools: Tools subagents are allowed to use. Defaults to the parent agent's
            tools. The model may restrict each spawn to a subset by name.
        instructions: Instructions given to every subagent.
        name: Base display name for subagents. Defaults to a parent-derived name.
        max_concurrent: Maximum subagents running at the same time per run; excess
            spawns wait for a slot. 0 or below disables the limit.
        max_total_per_run: Maximum spawn_agent calls per run; further calls return
            an error string to the model. 0 or below disables the limit.
        timeout_seconds: Wall-clock budget per spawn. On breach the subagent is
            cancelled and the tool result says so. Checked as the subagent's events
            arrive, so a subagent that emits no events cannot be interrupted
            mid-event. None or 0 and below disables the limit.
    """

    model: Optional[Model] = None
    models: Optional[Dict[str, Union[Model, Tuple[Model, str]]]] = None
    tools: Optional[List[Any]] = None
    instructions: Optional[str] = None
    name: Optional[str] = None
    max_concurrent: int = 5
    max_total_per_run: int = 20
    timeout_seconds: Optional[float] = None

    # Resolved in __post_init__: named options normalized to plain models + descriptions.
    _models: Optional[Dict[str, Model]] = field(default=None, init=False, repr=False)
    _model_descriptions: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.model is not None and self.models is not None:
            raise ValueError("Pass either SubagentsManager.model or SubagentsManager.models, not both")
        if self.models is not None and len(self.models) == 0:
            raise ValueError("SubagentsManager.models cannot be empty; omit it to inherit the parent agent's model")

        if self.model is not None:
            self._models = {"default": self.model}
        elif self.models is not None:
            self._models = {}
            for key, option in self.models.items():
                if isinstance(option, tuple):
                    self._models[key], self._model_descriptions[key] = option
                else:
                    self._models[key] = option

    # ------------------------------------------------------------------
    # Option resolution
    # ------------------------------------------------------------------

    def _resolve_models(self, parent: Agent) -> Dict[str, Model]:
        if self._models is not None:
            return self._models
        return {"default": parent.model}  # type: ignore[dict-item]

    def _resolve_allowed_tools(self, parent: Agent) -> Dict[str, Any]:
        """Build the name -> tool map of tools subagents may use."""
        source = self.tools
        if source is None:
            source = parent.tools if isinstance(parent.tools, list) else []

        allowed: Dict[str, Any] = {}
        for tool in source:
            if isinstance(tool, Toolkit):
                allowed[tool.name] = tool
            elif isinstance(tool, Function):
                allowed[tool.name] = tool
            elif callable(tool) and getattr(tool, "__name__", None):
                allowed[tool.__name__] = tool
            else:
                log_debug(f"Skipping tool {tool} for subagents: it has no selectable name")
        return allowed

    def _build_child(
        self,
        parent: Agent,
        model_key: str,
        tool_names: List[str],
        models: Dict[str, Model],
        allowed_tools: Dict[str, Any],
    ) -> Agent:
        """Build the child Agent for one spawn.

        Built fresh per spawn - no caching, so no state is retained on the manager
        or the parent between spawns. The child has no db and reuses the parent's
        already-constructed Model instance, so construction is cheap next to the
        LLM run it wraps, and concurrent spawns never share an Agent instance.
        """
        from agno.agent.agent import Agent

        return Agent(
            id=f"{parent.id}-subagent-{model_key}",
            name=f"{self.name or parent.name or 'Agent'} Subagent ({model_key})",
            model=models[model_key],
            tools=[allowed_tools[tool_name] for tool_name in tool_names],
            instructions=self.instructions,
            debug_mode=parent.debug_mode,
            store_events=parent.store_events,
        )

    def _validate_selection(
        self,
        model: Optional[str],
        tools: Optional[List[str]],
        models: Dict[str, Model],
        allowed_tools: Dict[str, Any],
    ) -> Union[str, Tuple[str, List[str]]]:
        """Validate the model's picks against the allowed options.

        The spawning model chooses a model option and (optionally) a tool subset per
        spawn; this checks both against what the manager actually allows, so the
        model cannot select anything it was not offered. On a bad pick it returns a
        corrective error string (yielded as the tool result so the LLM can fix its
        call) instead of raising; on success it returns the resolved
        (model_key, tool_names).
        """
        model_key = model or next(iter(models))
        if model_key not in models:
            return f"Unknown model option '{model_key}'. Choose one of: {', '.join(models)}"

        if tools:
            unknown = [tool_name for tool_name in tools if tool_name not in allowed_tools]
            if unknown:
                if not allowed_tools:
                    return "No tools are available to subagents. Call spawn_agent without the tools argument."
                return (
                    f"Unknown tool name(s) {', '.join(unknown)} for the subagent. "
                    f"Choose from: {', '.join(allowed_tools)}"
                )
            tool_names = list(dict.fromkeys(tools))
        else:
            tool_names = list(allowed_tools)
        return model_key, tool_names

    # ------------------------------------------------------------------
    # Per-run tool factory
    # ------------------------------------------------------------------

    def _build_description(self, models: Dict[str, Model], allowed_tools: Dict[str, Any]) -> str:
        model_lines = []
        for index, (key, option) in enumerate(models.items()):
            suffix = " (default)" if index == 0 else ""
            line = f"- {key}: {getattr(option, 'id', option)}{suffix}"
            description = self._model_descriptions.get(key)
            if description:
                line += f" - {description}"
            model_lines.append(line)
        description = _SPAWN_DESCRIPTION + "\n\nAvailable models:\n" + "\n".join(model_lines)
        if allowed_tools:
            tool_lines = [f"- {tool_name}" for tool_name in allowed_tools]
            description += "\n\nAvailable tools:\n" + "\n".join(tool_lines)
        else:
            description += "\n\nSubagents have no tools; they answer from the model alone."
        if self.max_total_per_run > 0:
            description += f"\n\nYou can spawn at most {self.max_total_per_run} subagents in this run."
        return description

    def get_parent_instructions(self) -> str:
        """Guidance added to the parent agent's system message."""
        return DEFAULT_INSTRUCTIONS

    def get_spawn_function(
        self,
        agent: Agent,
        run_context: RunContext,
        async_mode: bool = False,
    ) -> Function:
        """Build the spawn_agent tool for one run.

        Built per run (like Team delegate tools) so the tool description can list
        the real allowed options, including tools inherited from the parent, and so
        the per-run guardrails (spawn counter, concurrency slots) reset each run.
        """
        models = self._resolve_models(agent)
        allowed_tools = self._resolve_allowed_tools(agent)
        description = self._build_description(models=models, allowed_tools=allowed_tools)

        # Per-run guardrail state, shared by every spawn in this run.
        total_limit = self.max_total_per_run
        spawn_count = 0
        count_lock = threading.Lock()
        concurrent_limit = self.max_concurrent if self.max_concurrent > 0 else None
        sync_slots = threading.BoundedSemaphore(concurrent_limit) if concurrent_limit and not async_mode else None
        async_slots = asyncio.Semaphore(concurrent_limit) if concurrent_limit and async_mode else None
        timeout = self.timeout_seconds if self.timeout_seconds and self.timeout_seconds > 0 else None

        def _take_spawn_slot() -> Optional[str]:
            """Count a spawn against max_total_per_run; error string when exhausted."""
            nonlocal spawn_count
            with count_lock:
                if total_limit > 0 and spawn_count >= total_limit:
                    return (
                        f"Subagent limit for this run reached ({total_limit} spawns). Do the remaining work yourself."
                    )
                spawn_count += 1
                return None

        def spawn_agent(
            task: str, model: Optional[str] = None, tools: Optional[List[str]] = None
        ) -> Iterator[Union[RunOutputEvent, str]]:
            """Delegate a task to a subagent and return its result.

            Args:
                task (str): Complete, self-contained task description. The subagent
                    does not see this conversation, so include all context it needs
                    and the exact output to return.
                model (Optional[str]): Model option to run the subagent on, one of
                    the names listed in this tool's description. Omit to use the
                    default option.
                tools (Optional[List[str]]): Tool names the subagent may use, chosen
                    from the tool names listed in this tool's description. Omit to
                    allow all of them.

            Returns:
                str: The subagent's response.
            """
            selection = self._validate_selection(model=model, tools=tools, models=models, allowed_tools=allowed_tools)
            if isinstance(selection, str):
                yield selection
                return
            limit_error = _take_spawn_slot()
            if limit_error is not None:
                yield limit_error
                return
            model_key, tool_names = selection
            child = self._build_child(
                parent=agent, model_key=model_key, tool_names=tool_names, models=models, allowed_tools=allowed_tools
            )
            state_copy = copy(run_context.session_state)
            child_run_id = str(uuid4())
            child_output: Optional[RunOutput] = None
            streamed_content = False
            timed_out = False
            log_debug(f"Spawning subagent {child.id} for run {run_context.run_id}")
            if sync_slots is not None:
                sync_slots.acquire()
            try:
                if run_context.run_id is not None:
                    register_member_run(run_context.run_id, child_run_id)
                child_stream = child.run(
                    task,
                    user_id=run_context.user_id,
                    # Subagents run in the parent's session
                    session_id=run_context.session_id,
                    session_state=state_copy,  # Send a copy to the subagent
                    stream=True,
                    stream_events=True,
                    dependencies=run_context.dependencies,
                    metadata=run_context.metadata,
                    run_id=child_run_id,
                    yield_run_output=True,
                )
                deadline = time.monotonic() + timeout if timeout is not None else None
                draining_after_cancel = False
                for event in child_stream:
                    # Do NOT break out of the loop, the iterator needs to exit properly
                    if isinstance(event, RunOutput):
                        child_output = event
                        continue  # Don't yield the RunOutput, only yield events

                    if isinstance(event, _TERMINAL_EVENT_TYPES):
                        event.parent_run_id = event.parent_run_id or run_context.run_id
                        yield event
                        if isinstance(event, RunCancelledEvent):
                            draining_after_cancel = True
                        continue

                    if draining_after_cancel:
                        continue

                    event.parent_run_id = event.parent_run_id or run_context.run_id
                    if isinstance(event, RunContentEvent) and event.content:
                        streamed_content = True
                    yield event

                    try:
                        if run_context.run_id is not None:
                            raise_if_cancelled(run_context.run_id)
                    except RunCancelledException:
                        cancel_run(child_run_id)
                        draining_after_cancel = True
                        continue
                    if deadline is not None and time.monotonic() >= deadline:
                        cancel_run(child_run_id)
                        timed_out = True
                        draining_after_cancel = True
                        continue
                if draining_after_cancel and not timed_out:
                    raise RunCancelledException("")
            except RunCancelledException:
                _merge_state(run_context, state_copy)
                raise
            except Exception as e:
                log_error(f"Subagent task failed: {e}")
                _merge_state(run_context, state_copy)
                yield f"Subagent task failed: {str(e)}"
                return
            finally:
                if sync_slots is not None:
                    sync_slots.release()

            _merge_state(run_context, state_copy)
            if timed_out:
                yield f"Subagent task timed out after {timeout} seconds. Only the output above was produced."
                return
            yield from _final_result(child_output, streamed_content)

        async def aspawn_agent(
            task: str, model: Optional[str] = None, tools: Optional[List[str]] = None
        ) -> AsyncIterator[Union[RunOutputEvent, str]]:
            """Delegate a task to a subagent and return its result. Call spawn_agent
            multiple times in the same response to run subagents in parallel.

            Args:
                task (str): Complete, self-contained task description. The subagent
                    does not see this conversation, so include all context it needs
                    and the exact output to return.
                model (Optional[str]): Model option to run the subagent on, one of
                    the names listed in this tool's description. Omit to use the
                    default option.
                tools (Optional[List[str]]): Tool names the subagent may use, chosen
                    from the tool names listed in this tool's description. Omit to
                    allow all of them.

            Returns:
                str: The subagent's response.
            """
            selection = self._validate_selection(model=model, tools=tools, models=models, allowed_tools=allowed_tools)
            if isinstance(selection, str):
                yield selection
                return
            limit_error = _take_spawn_slot()
            if limit_error is not None:
                yield limit_error
                return
            model_key, tool_names = selection
            child = self._build_child(
                parent=agent, model_key=model_key, tool_names=tool_names, models=models, allowed_tools=allowed_tools
            )
            state_copy = copy(run_context.session_state)
            child_run_id = str(uuid4())
            child_output: Optional[RunOutput] = None
            streamed_content = False
            timed_out = False
            log_debug(f"Spawning subagent {child.id} for run {run_context.run_id}")
            if async_slots is not None:
                await async_slots.acquire()
            try:
                if run_context.run_id is not None:
                    await aregister_member_run(run_context.run_id, child_run_id)
                child_stream = child.arun(
                    task,
                    user_id=run_context.user_id,
                    # Subagents run in the parent's session
                    session_id=run_context.session_id,
                    session_state=state_copy,  # Send a copy to the subagent
                    stream=True,
                    stream_events=True,
                    dependencies=run_context.dependencies,
                    metadata=run_context.metadata,
                    run_id=child_run_id,
                    yield_run_output=True,
                )
                deadline = time.monotonic() + timeout if timeout is not None else None
                draining_after_cancel = False
                async for event in child_stream:
                    # Do NOT break out of the loop, the iterator needs to exit properly
                    if isinstance(event, RunOutput):
                        child_output = event
                        continue  # Don't yield the RunOutput, only yield events

                    if isinstance(event, _TERMINAL_EVENT_TYPES):
                        event.parent_run_id = event.parent_run_id or run_context.run_id
                        yield event
                        if isinstance(event, RunCancelledEvent):
                            draining_after_cancel = True
                        continue

                    if draining_after_cancel:
                        continue

                    event.parent_run_id = event.parent_run_id or run_context.run_id
                    if isinstance(event, RunContentEvent) and event.content:
                        streamed_content = True
                    yield event

                    try:
                        if run_context.run_id is not None:
                            await araise_if_cancelled(run_context.run_id)
                    except RunCancelledException:
                        await acancel_run(child_run_id)
                        draining_after_cancel = True
                        continue
                    if deadline is not None and time.monotonic() >= deadline:
                        await acancel_run(child_run_id)
                        timed_out = True
                        draining_after_cancel = True
                        continue
                if draining_after_cancel and not timed_out:
                    raise RunCancelledException("")
            except RunCancelledException:
                _merge_state(run_context, state_copy)
                raise
            except Exception as e:
                log_error(f"Subagent task failed: {e}")
                _merge_state(run_context, state_copy)
                yield f"Subagent task failed: {str(e)}"
                return
            finally:
                if async_slots is not None:
                    async_slots.release()

            _merge_state(run_context, state_copy)
            if timed_out:
                yield f"Subagent task timed out after {timeout} seconds. Only the output above was produced."
                return
            for item in _final_result(child_output, streamed_content):
                yield item

        return Function(
            name="spawn_agent",
            entrypoint=aspawn_agent if async_mode else spawn_agent,
            description=description,
            instructions=self.get_parent_instructions(),
            add_instructions=True,
        )
