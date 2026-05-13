"""AgentSpawnHandler — one spawn invents and runs a single specialist agent.

This is the leaf handler. Composite handlers (Condition / Loop / Parallel / Router)
delegate to this for each child agent spawn they orchestrate.

Behaviorally identical to the previous _do_spawn_sync / _do_spawn_async on
DynamicWorkflowDriver — just extracted into a class so other handlers can compose it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.agent import Agent
from agno.models.base import Model
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, log_info, log_warning
from agno.workflow.dynamic_handlers.base import _RunContext, _SpawnHandler, _StreamBridge, _TrailBuilder, _TrailNode
from agno.workflow.step import Step
from agno.workflow.types import StepInput

if TYPE_CHECKING:
    from agno.workflow.types import StepOutput


def _resolve_tools(
    requested_names: Optional[List[str]],
    allowed_tools: Optional[List[Union[Toolkit, Callable, Function]]],
    allow_tool_selection: bool,
) -> List[Union[Toolkit, Callable, Function]]:
    """Resolve a name-list from the LLM into actual tool objects, filtered by allowed_tools.

    Function-level whitelist filtering — Toolkits are decomposed so only the permitted
    Function members are extracted (preventing whole-toolkit grants by name).
    """
    if not allowed_tools:
        return []
    if not allow_tool_selection or requested_names is None:
        return list(allowed_tools)
    if not requested_names:
        return []

    permitted = set(requested_names)
    resolved: List[Union[Toolkit, Callable, Function]] = []

    for tool in allowed_tools:
        if isinstance(tool, Toolkit):
            for fn in tool.functions.values():
                if fn.name in permitted:
                    resolved.append(fn)
        elif isinstance(tool, Function):
            if tool.name in permitted:
                resolved.append(tool)
        elif callable(tool):
            name = getattr(tool, "__name__", None)
            if name and name in permitted:
                resolved.append(tool)
    return resolved


def _summarize_output(content: Any, max_chars: int) -> str:
    """Cap an agent output for return to the driver's context."""
    if content is None:
        return ""
    if not isinstance(content, str):
        try:
            content = str(content)
        except Exception:
            return ""
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    return content[: max_chars - 3] + "..."


class _AgentSpawnHandler(_SpawnHandler):
    """Build one ephemeral Agent, wrap it in a Step, run it through Step.execute(_stream).

    Centralizes the spawn-an-agent flow. Composite handlers (Condition, Loop, etc.)
    own their tree node and delegate the per-child agent spawn here.
    """

    def __init__(
        self,
        *,
        model: Optional[Model],
        allowed_tools: Optional[List[Union[Toolkit, Callable, Function]]],
        allow_tool_selection: bool,
        model_tiers: Optional[Dict[str, str]],
        allow_model_tier_selection: bool,
        step_summary_max_chars: int,
        show_step_output: bool,
        log_step_runs: bool,
    ):
        self.model = model
        self.allowed_tools = allowed_tools
        self.allow_tool_selection = allow_tool_selection
        self.model_tiers = model_tiers
        self.allow_model_tier_selection = allow_model_tier_selection
        self.step_summary_max_chars = step_summary_max_chars
        self.show_step_output = show_step_output
        self.log_step_runs = log_step_runs

    # ---- public spawn API ---------------------------------------------------

    def spawn(
        self,
        ctx: _RunContext,
        trail: _TrailBuilder,
        stream: _StreamBridge,
        *,
        role: str,
        instructions: str,
        input: str,
        tools: Optional[List[str]] = None,
        model_tier: Optional[str] = None,
        expected_output: Optional[str] = None,
        parent_id: Optional[str] = None,
        as_child: bool = False,
    ) -> _TrailNode:
        """Sync agent spawn.

        When `as_child=True`, the resulting node is NOT added to trail.root_children
        — the caller (a composite handler) will attach it under its own composite node.
        The leaf ExecutedStepRecord is still appended to trail.leaf_records.

        Returns the built _TrailNode either way; caller can inspect `.output` for
        the spawned agent's StepOutput.
        """
        return self._spawn_impl(
            ctx, trail, stream,
            role=role, instructions=instructions, input=input,
            tools=tools, model_tier=model_tier, expected_output=expected_output,
            parent_id=parent_id, as_child=as_child, is_async=False,
        )

    async def aspawn(
        self,
        ctx: _RunContext,
        trail: _TrailBuilder,
        stream: _StreamBridge,
        *,
        role: str,
        instructions: str,
        input: str,
        tools: Optional[List[str]] = None,
        model_tier: Optional[str] = None,
        expected_output: Optional[str] = None,
        parent_id: Optional[str] = None,
        as_child: bool = False,
    ) -> _TrailNode:
        """Async agent spawn — same as `spawn` but routes through Step.aexecute."""
        return await self._aspawn_impl(
            ctx, trail, stream,
            role=role, instructions=instructions, input=input,
            tools=tools, model_tier=model_tier, expected_output=expected_output,
            parent_id=parent_id, as_child=as_child,
        )

    # ---- shared internals ---------------------------------------------------

    def _resolve_model(self, requested_tier: Optional[str]) -> Optional[Model]:
        if not (self.allow_model_tier_selection and requested_tier and self.model_tiers):
            return self.model
        model_id = self.model_tiers.get(requested_tier)
        if not model_id:
            log_warning(f"Spawned agent requested unknown model_tier {requested_tier!r}; falling back to driver model")
            return self.model
        try:
            from agno.models.utils import get_model
            return get_model(model_id)  # type: ignore[return-value]
        except Exception as e:
            log_warning(f"Failed to resolve model_tier {requested_tier!r}: {e}; falling back to driver model")
            return self.model

    def _build_agent(
        self,
        *,
        role: str,
        instructions: str,
        tools: Optional[List[str]],
        model_tier: Optional[str],
    ) -> Tuple[Agent, List[str]]:
        resolved_tools = _resolve_tools(tools, self.allowed_tools, self.allow_tool_selection)
        resolved_model = self._resolve_model(model_tier)
        agent = Agent(
            name=role,
            model=resolved_model,
            instructions=instructions,
            tools=resolved_tools if resolved_tools else None,
            db=None,
            telemetry=False,
            num_history_runs=0,
        )
        resolved_tool_names = [getattr(t, "name", getattr(t, "__name__", "")) for t in resolved_tools]
        resolved_tool_names = [n for n in resolved_tool_names if n]
        return agent, resolved_tool_names

    def _build_step_input(self, ctx: _RunContext, trail: _TrailBuilder, *, spawn_input_text: str) -> StepInput:
        prev = trail.previous_step_outputs
        previous_step_content = None
        if prev:
            last_output = list(prev.values())[-1]
            previous_step_content = last_output.content if last_output is not None else None

        ei = ctx.execution_input
        return StepInput(
            input=spawn_input_text,
            previous_step_content=previous_step_content,
            previous_step_outputs=dict(prev) if prev else None,
            additional_data=ei.additional_data if ei else None,
            images=list(ei.images or []) if ei else [],
            videos=list(ei.videos or []) if ei else [],
            audio=list(ei.audio or []) if ei else [],
            files=list(ei.files or []) if ei else [],
            workflow_session=ctx.workflow_session,
        )

    def _emit_spawned_event(
        self,
        ctx: _RunContext,
        stream: _StreamBridge,
        *,
        iteration: int,
        role: str,
        instructions: str,
        input: str,
        tools: List[str],
        model_tier: Optional[str],
    ) -> None:
        try:
            from agno.run.workflow import StepSpawnedEvent
            wrr = ctx.workflow_run_response
            event = StepSpawnedEvent(
                iteration=iteration,
                role=role,
                instructions=instructions[:200],
                input=input[:200],
                tool_names=tools or None,
                model_tier=model_tier,
                run_id=wrr.run_id if wrr else None,
                session_id=wrr.session_id if wrr else None,
                workflow_id=wrr.workflow_id if wrr else None,
                workflow_name=wrr.workflow_name if wrr else None,
            )
            if wrr is not None:
                if wrr.events is None:
                    wrr.events = []
                wrr.events.append(event)
            stream.emit(event)
        except Exception as e:
            log_debug(f"_AgentSpawnHandler: could not emit StepSpawnedEvent: {e}")

    def _make_record_and_attach(
        self,
        ctx: _RunContext,
        trail: _TrailBuilder,
        *,
        iteration: int,
        role: str,
        instructions: str,
        input: str,
        step_output: "StepOutput",
        step_id: str,
        resolved_tool_names: List[str],
        model_tier: Optional[str],
        parent_id: Optional[str],
        as_child: bool,
    ) -> _TrailNode:
        from agno.run.workflow import ExecutedStepRecord

        content_str = (
            step_output.content
            if isinstance(step_output.content, str)
            else (str(step_output.content) if step_output.content is not None else "")
        )

        record = ExecutedStepRecord(
            iteration=iteration,
            role=role,
            instructions=instructions,
            input=input,
            output_content=content_str,
            tools=resolved_tool_names or None,
            model_tier=model_tier,
            step_id=step_id,
            parent_id=parent_id,
        )
        trail.add_leaf_record(record)
        trail.previous_step_outputs[role] = step_output

        if ctx.workflow_run_response is not None and not as_child:
            # Top-level agent spawns go straight into step_results.
            # Children of a composite are attached by the composite handler instead.
            ctx.workflow_run_response.step_results.append(step_output)

        node = _TrailNode(
            kind="agent",
            step_id=step_id,
            parent_id=parent_id,
            iteration=iteration,
            role=role,
            instructions=instructions,
            input=input,
            output=step_output,
            tools=resolved_tool_names or None,
            model_tier=model_tier,
        )

        if not as_child:
            trail.add_top_level(node)
        return node

    # ---- the two implementations -------------------------------------------

    def _spawn_impl(
        self,
        ctx: _RunContext,
        trail: _TrailBuilder,
        stream: _StreamBridge,
        *,
        role: str,
        instructions: str,
        input: str,
        tools: Optional[List[str]],
        model_tier: Optional[str],
        expected_output: Optional[str],
        parent_id: Optional[str],
        as_child: bool,
        is_async: bool,  # unused here; kept for symmetry
    ) -> _TrailNode:
        iteration = trail.claim_iteration()
        if iteration is None:
            # Cap exceeded — caller is responsible for surfacing the message to the LLM.
            raise _MaxStepsExceededError(trail.max_steps)

        agent, resolved_tool_names = self._build_agent(
            role=role, instructions=instructions, tools=tools, model_tier=model_tier
        )

        if self.log_step_runs:
            log_info(
                f"DynamicWorkflowDriver spawning [{iteration}] role={role!r} "
                f"tools={resolved_tool_names} tier={model_tier}"
            )

        self._emit_spawned_event(
            ctx, stream,
            iteration=iteration, role=role, instructions=instructions, input=input,
            tools=resolved_tool_names, model_tier=model_tier,
        )

        spawn_input_text = input if not expected_output else f"{input}\n\nExpected output: {expected_output}"
        step_input = self._build_step_input(ctx, trail, spawn_input_text=spawn_input_text)

        step = Step(name=role, agent=agent)
        step.step_id = str(uuid4())

        if stream.active:
            from agno.workflow.types import StepOutput as _StepOutput
            step_output: Optional["StepOutput"] = None
            for ev in step.execute_stream(
                step_input,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                stream_events=stream.stream_events,
                stream_executor_events=stream.stream_executor_events,
                workflow_run_response=ctx.workflow_run_response,
                run_context=ctx.run_context,
                store_executor_outputs=ctx.store_executor_outputs,
                workflow_session=ctx.workflow_session,
                add_workflow_history_to_steps=ctx.add_workflow_history_to_steps,
                num_history_runs=ctx.num_history_runs,
                background_tasks=ctx.background_tasks,
                add_dependencies_to_context=ctx.add_dependencies_to_context,
                add_session_state_to_context=ctx.add_session_state_to_context,
            ):
                if isinstance(ev, _StepOutput):
                    step_output = ev
                else:
                    stream.emit(ev)
            if step_output is None:
                raise RuntimeError(f"Spawn {role!r} produced no StepOutput")
        else:
            step_output = step.execute(
                step_input,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                workflow_run_response=ctx.workflow_run_response,
                run_context=ctx.run_context,
                store_executor_outputs=ctx.store_executor_outputs,
                workflow_session=ctx.workflow_session,
                add_workflow_history_to_steps=ctx.add_workflow_history_to_steps,
                num_history_runs=ctx.num_history_runs,
                background_tasks=ctx.background_tasks,
                add_dependencies_to_context=ctx.add_dependencies_to_context,
                add_session_state_to_context=ctx.add_session_state_to_context,
            )

        if self.show_step_output:
            print(f"--- DynamicWorkflow spawn [{iteration}] {role} ---")
            print(step_output.content)
            print("--- end ---")

        return self._make_record_and_attach(
            ctx, trail,
            iteration=iteration, role=role, instructions=instructions, input=input,
            step_output=step_output, step_id=step.step_id,
            resolved_tool_names=resolved_tool_names, model_tier=model_tier,
            parent_id=parent_id, as_child=as_child,
        )

    async def _aspawn_impl(
        self,
        ctx: _RunContext,
        trail: _TrailBuilder,
        stream: _StreamBridge,
        *,
        role: str,
        instructions: str,
        input: str,
        tools: Optional[List[str]],
        model_tier: Optional[str],
        expected_output: Optional[str],
        parent_id: Optional[str],
        as_child: bool,
    ) -> _TrailNode:
        iteration = trail.claim_iteration()
        if iteration is None:
            raise _MaxStepsExceededError(trail.max_steps)

        agent, resolved_tool_names = self._build_agent(
            role=role, instructions=instructions, tools=tools, model_tier=model_tier
        )

        if self.log_step_runs:
            log_info(
                f"DynamicWorkflowDriver aspawning [{iteration}] role={role!r} "
                f"tools={resolved_tool_names} tier={model_tier}"
            )

        self._emit_spawned_event(
            ctx, stream,
            iteration=iteration, role=role, instructions=instructions, input=input,
            tools=resolved_tool_names, model_tier=model_tier,
        )

        spawn_input_text = input if not expected_output else f"{input}\n\nExpected output: {expected_output}"
        step_input = self._build_step_input(ctx, trail, spawn_input_text=spawn_input_text)

        step = Step(name=role, agent=agent)
        step.step_id = str(uuid4())

        step_output = await step.aexecute(
            step_input,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            workflow_run_response=ctx.workflow_run_response,
            run_context=ctx.run_context,
            store_executor_outputs=ctx.store_executor_outputs,
            workflow_session=ctx.workflow_session,
            add_workflow_history_to_steps=ctx.add_workflow_history_to_steps,
            num_history_runs=ctx.num_history_runs,
            background_tasks=ctx.background_tasks,
            add_dependencies_to_context=ctx.add_dependencies_to_context,
            add_session_state_to_context=ctx.add_session_state_to_context,
        )

        if self.show_step_output:
            print(f"--- DynamicWorkflow spawn [{iteration}] {role} ---")
            print(step_output.content)
            print("--- end ---")

        return self._make_record_and_attach(
            ctx, trail,
            iteration=iteration, role=role, instructions=instructions, input=input,
            step_output=step_output, step_id=step.step_id,
            resolved_tool_names=resolved_tool_names, model_tier=model_tier,
            parent_id=parent_id, as_child=as_child,
        )

    # ---- summary helper for tool-result returns -----------------------------

    def summary_for_tool_result(self, step_output: "StepOutput") -> str:
        content = step_output.content if step_output is not None else ""
        content_str = content if isinstance(content, str) else (str(content) if content is not None else "")
        return _summarize_output(content_str, self.step_summary_max_chars)


class _MaxStepsExceededError(Exception):
    """Raised by the agent spawn handler when the run has hit max_steps.

    The driver tool closure catches this and returns a string to the LLM telling it
    to finalize without spawning more.
    """

    def __init__(self, max_steps: int):
        super().__init__(f"max_steps ({max_steps}) reached")
        self.max_steps = max_steps
