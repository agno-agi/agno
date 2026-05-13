"""DynamicWorkflowDriver - workflow-level mirror of dynamic subagents (PR #7387).

A DynamicWorkflowDriver lets a workflow expand itself at runtime: instead of declaring a
static list of steps, the user hands a driver to `Workflow(steps=driver.as_workflow_function())`
and the driver's underlying LLM invents new agents on demand by calling a `spawn_agent` tool.
Each spawn creates a fresh Agent with the role/instructions/tools the LLM chose, runs it,
records the result, and returns only a short summary back to the driver's context.

The output of `Workflow.run(...)` will have:
- `content`: the driver's final response after all spawns
- `executed_steps`: the canonical trail (list of ExecutedStepRecord) of what actually ran
- `step_results`: the same trail re-expressed as StepOutput objects for compatibility with
  the rest of the workflow ecosystem

Out of scope for v0: spawn_parallel / spawn_loop / spawn_condition (deferred to v0.1),
recursive dynamic workflows (spawned agents cannot themselves spawn), HITL on spawns.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.agent import Agent
from agno.models.base import Model
from agno.run.workflow import ExecutedStepRecord
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, log_info, log_warning
from agno.workflow.step import Step
from agno.workflow.types import StepInput

if TYPE_CHECKING:
    from agno.run.base import RunContext
    from agno.run.workflow import WorkflowRunOutput
    from agno.session.workflow import WorkflowSession
    from agno.workflow.types import StepOutput, WorkflowExecutionInput


_DEFAULT_DRIVER_INSTRUCTIONS = """You are the ORCHESTRATOR of a dynamic workflow. You do NOT produce content yourself. You delegate every meaningful sub-task to a specialist agent via the `spawn_agent` tool, then assemble their outputs into the final response.

You have exactly one tool: `spawn_agent(role, instructions, input, tools?, model_tier?, expected_output?)`. Each call invents a fresh specialist agent — you pick its role, write its instructions, pick its tools — runs it on a focused sub-task, and returns a short summary of its output to you. The full output is recorded in the workflow trail.

HARD RULES (these are non-negotiable):
1. You MUST call spawn_agent at least once before producing any final response. Producing a final answer with zero spawns is FORBIDDEN.
2. Do NOT answer the user from your own training knowledge. Even if you "know" the answer, you must still delegate the research/analysis/writing to a spawned specialist. Your role is to orchestrate, not to be the expert.
3. Each spawn must have a clear, narrow purpose (e.g. "research X", "verify claims in Y", "write the final summary"). Do not spawn one giant generalist agent — break the task into specialist steps.
4. Use the `tools` argument to give the spawned agent only the capabilities it needs. Omit `tools` when no external capabilities are needed.
5. After spawning enough specialists to cover the user's task, stop spawning and write a short final response that synthesizes their outputs. Do not re-do work that a specialist already did.

Pattern for most tasks:
  spawn_agent(role="researcher", ...) -> get facts/data
  [optionally] spawn_agent(role="critic_or_fact_checker", ...) -> verify
  spawn_agent(role="writer_or_summarizer", ...) -> produce the deliverable
  -> Then your final response simply returns the writer's output (or a tightened version).
"""


@dataclass
class _SpawnState:
    """Mutable state shared between the driver function and the spawn tool closure.

    Carries both the running trail and the workflow execution context that each spawn
    needs to participate in the static-path infrastructure (Step.execute → events,
    step_executor_runs persistence, retries, error policy, history, media flow).
    """

    trail_outputs: List[Any] = field(default_factory=list)
    executed_steps: List[ExecutedStepRecord] = field(default_factory=list)
    # previous_step_outputs is keyed by role and grows after each successful spawn;
    # it's what we pass into StepInput so each spawn sees what ran before it.
    previous_step_outputs: Dict[str, "StepOutput"] = field(default_factory=dict)
    iteration: int = 0
    spawn_count: int = 0

    # Workflow execution context (forwarded into Step.execute on each spawn):
    workflow: Optional[Any] = None
    workflow_run_response: Optional["WorkflowRunOutput"] = None
    run_context: Optional["RunContext"] = None
    workflow_session: Optional["WorkflowSession"] = None
    execution_input: Optional["WorkflowExecutionInput"] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    store_executor_outputs: bool = True
    add_workflow_history_to_steps: Optional[bool] = None
    num_history_runs: int = 3
    background_tasks: Optional[Any] = None
    add_dependencies_to_context: Optional[bool] = None
    add_session_state_to_context: Optional[bool] = None

    # Streaming bridge. When set (by stream_call), each event from Step.execute_stream
    # and each StepSpawnedEvent is pushed here so the workflow's outer generator can
    # yield it in real time. None for non-streaming runs.
    event_sink: Optional[Callable[[Any], None]] = None
    stream_events: bool = False
    stream_executor_events: bool = True


def _resolve_tools(
    requested_names: Optional[List[str]],
    allowed_tools: Optional[List[Union[Toolkit, Callable, Function]]],
    allow_tool_selection: bool,
) -> List[Union[Toolkit, Callable, Function]]:
    """Resolve a name-list from the LLM into actual tool objects, filtered by allowed_tools.

    Mirrors the Function-level whitelist filtering from PR #7387's SubAgentToolkit._resolve_tools:
    Toolkits are decomposed so only their permitted Function members are extracted, never the
    whole toolkit (preventing whitelist bypass).
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


class DynamicWorkflowDriver:
    """Agent-driven dynamic workflow expansion.

    Two ways to drive expansion, same `steps=driver` DX:

    1. **LLM-driven (default).** The driver runs as an LLM agent with a single tool,
       `spawn_agent`. Each spawn invents a fresh specialist agent (role, instructions,
       tools, optional model tier), runs it, and returns a short summary back to the
       driver. The driver iterates until it produces a final response or `max_steps`
       is hit.

           driver = DynamicWorkflowDriver(model=..., instructions="...", allowed_tools=[...])
           wf = Workflow(name="...", steps=driver)

    2. **Python-driven.** Pass a `custom_driver` callable `(workflow_input, spawn) -> str`.
       The driver skips the LLM and runs your Python function instead. Same spawn semantics.

           def my_driver(workflow_input, spawn):
               a = spawn(role="researcher", instructions="...", input=workflow_input)
               return spawn(role="summarizer", instructions="...", input=a)

           driver = DynamicWorkflowDriver(model=..., custom_driver=my_driver)
           wf = Workflow(name="...", steps=driver)
    """

    def __init__(
        self,
        *,
        model: Optional[Model] = None,
        instructions: Optional[str] = None,
        allowed_tools: Optional[List[Union[Toolkit, Callable, Function]]] = None,
        allow_tool_selection: bool = True,
        model_tiers: Optional[Dict[str, str]] = None,
        allow_model_tier_selection: bool = False,
        tier_hints: Optional[Dict[str, str]] = None,
        max_steps: int = 10,
        step_summary_max_chars: int = 1200,
        show_step_output: bool = False,
        log_step_runs: bool = True,
        name: str = "dynamic_workflow_driver",
        custom_driver: Optional[Callable[[str, Callable], str]] = None,
    ):
        if custom_driver is None and model is None:
            raise ValueError(
                "DynamicWorkflowDriver requires either `model=` (LLM-driven mode) "
                "or `custom_driver=` (Python-driven mode)."
            )

        self.model = model
        self.user_instructions = instructions
        self.allowed_tools = allowed_tools
        self.allow_tool_selection = allow_tool_selection
        self.model_tiers = model_tiers
        self.allow_model_tier_selection = allow_model_tier_selection
        self.tier_hints = tier_hints
        self.max_steps = max_steps
        self.step_summary_max_chars = step_summary_max_chars
        self.show_step_output = show_step_output
        self.log_step_runs = log_step_runs
        self.name = name
        self.custom_driver = custom_driver

    def _build_instructions(self) -> str:
        parts: List[str] = [_DEFAULT_DRIVER_INSTRUCTIONS]
        if self.user_instructions:
            parts.append("\nUser-provided goal:\n" + self.user_instructions.strip())

        if self.allowed_tools:
            tool_names = self._available_tool_names()
            if tool_names:
                parts.append("\nTools available to spawned agents (pass any subset as `tools`):")
                for n in tool_names:
                    parts.append(f"- {n}")

        if self.allow_model_tier_selection and self.model_tiers:
            parts.append("\nAvailable model tiers (pass as `model_tier`):")
            hints = dict(self.tier_hints or {})
            for tier in self.model_tiers:
                hint = hints.get(tier, "")
                parts.append(f"- {tier}" + (f" ({hint})" if hint else ""))

        return "\n".join(parts)

    def _available_tool_names(self) -> List[str]:
        names: List[str] = []
        if not self.allowed_tools:
            return names
        for tool in self.allowed_tools:
            if isinstance(tool, Toolkit):
                names.extend(tool.functions.keys())
            elif isinstance(tool, Function):
                names.append(tool.name)
            elif callable(tool):
                name = getattr(tool, "__name__", None)
                if name:
                    names.append(name)
        return names

    def _resolve_model(self, requested_tier: Optional[str]) -> Model:
        """Resolve the model for a spawned agent: requested tier > driver's model."""
        if not (self.allow_model_tier_selection and requested_tier and self.model_tiers):
            return self.model

        model_id = self.model_tiers.get(requested_tier)
        if not model_id:
            log_warning(f"Spawned agent requested unknown model_tier '{requested_tier}', falling back to driver model")
            return self.model

        try:
            from agno.models.utils import get_model

            return get_model(model_id)  # type: ignore[return-value]
        except Exception as e:
            log_warning(
                f"Failed to resolve model_tier '{requested_tier}' to a Model: {e}; falling back to driver model"
            )
            return self.model

    def _build_spawned_agent(
        self,
        *,
        role: str,
        instructions: str,
        tools: Optional[List[str]],
        model_tier: Optional[str],
    ) -> Tuple[Agent, List[str]]:
        """Create the ephemeral specialist agent for one spawn."""
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

    def _build_step_input(self, state: _SpawnState, *, spawn_input_text: str) -> StepInput:
        """Build a StepInput for a single spawn.

        The driver's per-spawn `input` argument replaces the workflow input for this step
        (so each specialist sees its own focused task). Previous spawns are exposed through
        `previous_step_outputs` so the specialist can reference them by role if needed.
        Media and additional_data are forwarded from the workflow's execution_input.
        """
        prev = state.previous_step_outputs
        previous_step_content = None
        if prev:
            last_output = list(prev.values())[-1]
            previous_step_content = last_output.content if last_output is not None else None

        ei = state.execution_input
        return StepInput(
            input=spawn_input_text,
            previous_step_content=previous_step_content,
            previous_step_outputs=dict(prev) if prev else None,
            additional_data=ei.additional_data if ei else None,
            images=list(ei.images or []) if ei else [],
            videos=list(ei.videos or []) if ei else [],
            audio=list(ei.audio or []) if ei else [],
            files=list(ei.files or []) if ei else [],
            workflow_session=state.workflow_session,
        )

    def _do_spawn_sync(
        self,
        state: _SpawnState,
        *,
        role: str,
        instructions: str,
        input: str,
        tools: Optional[List[str]] = None,
        model_tier: Optional[str] = None,
        expected_output: Optional[str] = None,
    ) -> str:
        if state.spawn_count >= self.max_steps:
            msg = (
                f"max_steps ({self.max_steps}) reached. No more agents may be spawned. "
                "Produce your final response now based on the spawns so far."
            )
            log_warning(f"DynamicWorkflowDriver: {msg}")
            return msg

        state.spawn_count += 1
        iteration = state.iteration
        state.iteration += 1

        agent, resolved_tool_names = self._build_spawned_agent(
            role=role, instructions=instructions, tools=tools, model_tier=model_tier
        )

        if self.log_step_runs:
            log_info(
                f"DynamicWorkflowDriver spawning [{iteration}] role='{role}' "
                f"tools={resolved_tool_names} tier={model_tier}"
            )

        self._emit_spawned_event(
            state,
            iteration=iteration,
            role=role,
            instructions=instructions,
            input=input,
            tools=resolved_tool_names,
            model_tier=model_tier,
        )

        # Route the spawn through Step.execute(_stream) so it participates in the
        # static-path infrastructure: StepStarted/Completed events, step_executor_runs
        # persistence (full RunOutput when store_executor_outputs=True), retries, error
        # policy, media flow, history. The Step is ephemeral — built per spawn — but
        # the execution machinery is identical to a static-workflow step.
        spawn_input_text = input if not expected_output else f"{input}\n\nExpected output: {expected_output}"
        step_input = self._build_step_input(state, spawn_input_text=spawn_input_text)

        step = Step(name=role, agent=agent)
        step.step_id = str(uuid4())

        try:
            if state.event_sink is not None:
                # Streaming path: forward each yielded event to the sink in real time.
                # The final StepOutput is the last item yielded.
                from agno.workflow.types import StepOutput as _StepOutput

                step_output = None
                for ev in step.execute_stream(
                    step_input,
                    session_id=state.session_id,
                    user_id=state.user_id,
                    stream_events=state.stream_events,
                    stream_executor_events=state.stream_executor_events,
                    workflow_run_response=state.workflow_run_response,
                    run_context=state.run_context,
                    store_executor_outputs=state.store_executor_outputs,
                    workflow_session=state.workflow_session,
                    add_workflow_history_to_steps=state.add_workflow_history_to_steps,
                    num_history_runs=state.num_history_runs,
                    background_tasks=state.background_tasks,
                    add_dependencies_to_context=state.add_dependencies_to_context,
                    add_session_state_to_context=state.add_session_state_to_context,
                ):
                    if isinstance(ev, _StepOutput):
                        step_output = ev
                    else:
                        state.event_sink(ev)
                if step_output is None:
                    raise RuntimeError(f"Step '{role}' produced no StepOutput")
            else:
                step_output = step.execute(
                    step_input,
                    session_id=state.session_id,
                    user_id=state.user_id,
                    workflow_run_response=state.workflow_run_response,
                    run_context=state.run_context,
                    store_executor_outputs=state.store_executor_outputs,
                    workflow_session=state.workflow_session,
                    add_workflow_history_to_steps=state.add_workflow_history_to_steps,
                    num_history_runs=state.num_history_runs,
                    background_tasks=state.background_tasks,
                    add_dependencies_to_context=state.add_dependencies_to_context,
                    add_session_state_to_context=state.add_session_state_to_context,
                )
        except Exception as e:
            log_warning(f"DynamicWorkflowDriver spawn '{role}' failed: {e}")
            return f"Error running spawned agent '{role}': {e}"

        content_str = step_output.content if isinstance(step_output.content, str) else (
            str(step_output.content) if step_output.content is not None else ""
        )

        if self.show_step_output:
            print(f"--- DynamicWorkflow spawn [{iteration}] {role} ---")
            print(content_str)
            print("--- end ---")

        record = ExecutedStepRecord(
            iteration=iteration,
            role=role,
            instructions=instructions,
            input=input,
            output_content=content_str,
            tools=resolved_tool_names or None,
            model_tier=model_tier,
            step_id=step.step_id,
        )
        state.executed_steps.append(record)
        state.trail_outputs.append(content_str)
        state.previous_step_outputs[role] = step_output

        # Append the StepOutput to workflow_run_response.step_results so the canonical
        # static-workflow trail is populated. Step.execute already appended the agent's
        # full RunOutput to step_executor_runs if store_executor_outputs=True.
        if state.workflow_run_response is not None:
            state.workflow_run_response.step_results.append(step_output)

        return _summarize_output(content_str, self.step_summary_max_chars)

    async def _do_spawn_async(
        self,
        state: _SpawnState,
        *,
        role: str,
        instructions: str,
        input: str,
        tools: Optional[List[str]] = None,
        model_tier: Optional[str] = None,
        expected_output: Optional[str] = None,
    ) -> str:
        if state.spawn_count >= self.max_steps:
            msg = (
                f"max_steps ({self.max_steps}) reached. No more agents may be spawned. "
                "Produce your final response now based on the spawns so far."
            )
            log_warning(f"DynamicWorkflowDriver: {msg}")
            return msg

        state.spawn_count += 1
        iteration = state.iteration
        state.iteration += 1

        agent, resolved_tool_names = self._build_spawned_agent(
            role=role, instructions=instructions, tools=tools, model_tier=model_tier
        )

        if self.log_step_runs:
            log_info(
                f"DynamicWorkflowDriver aspawning [{iteration}] role='{role}' "
                f"tools={resolved_tool_names} tier={model_tier}"
            )

        self._emit_spawned_event(
            state,
            iteration=iteration,
            role=role,
            instructions=instructions,
            input=input,
            tools=resolved_tool_names,
            model_tier=model_tier,
        )

        # Route async spawn through Step.aexecute — same integration story as sync.
        spawn_input_text = input if not expected_output else f"{input}\n\nExpected output: {expected_output}"
        step_input = self._build_step_input(state, spawn_input_text=spawn_input_text)

        step = Step(name=role, agent=agent)
        step.step_id = str(uuid4())

        try:
            step_output = await step.aexecute(
                step_input,
                session_id=state.session_id,
                user_id=state.user_id,
                workflow_run_response=state.workflow_run_response,
                run_context=state.run_context,
                store_executor_outputs=state.store_executor_outputs,
                workflow_session=state.workflow_session,
                add_workflow_history_to_steps=state.add_workflow_history_to_steps,
                num_history_runs=state.num_history_runs,
                background_tasks=state.background_tasks,
                add_dependencies_to_context=state.add_dependencies_to_context,
                add_session_state_to_context=state.add_session_state_to_context,
            )
        except Exception as e:
            log_warning(f"DynamicWorkflowDriver spawn '{role}' failed: {e}")
            return f"Error running spawned agent '{role}': {e}"

        content_str = step_output.content if isinstance(step_output.content, str) else (
            str(step_output.content) if step_output.content is not None else ""
        )

        if self.show_step_output:
            print(f"--- DynamicWorkflow spawn [{iteration}] {role} ---")
            print(content_str)
            print("--- end ---")

        record = ExecutedStepRecord(
            iteration=iteration,
            role=role,
            instructions=instructions,
            input=input,
            output_content=content_str,
            tools=resolved_tool_names or None,
            model_tier=model_tier,
            step_id=step.step_id,
        )
        state.executed_steps.append(record)
        state.trail_outputs.append(content_str)
        state.previous_step_outputs[role] = step_output

        if state.workflow_run_response is not None:
            state.workflow_run_response.step_results.append(step_output)

        return _summarize_output(content_str, self.step_summary_max_chars)

    def _emit_spawned_event(
        self,
        state: _SpawnState,
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

            wrr = state.workflow_run_response
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
            if state.event_sink is not None:
                state.event_sink(event)
        except Exception as e:
            log_debug(f"DynamicWorkflowDriver: could not emit StepSpawnedEvent: {e}")

    def _build_spawn_tool_sync(self, state: _SpawnState) -> Callable:
        if self.allow_model_tier_selection and self.model_tiers:

            def spawn_agent(
                role: str,
                instructions: str,
                input: str,
                tools: Optional[List[str]] = None,
                model_tier: Optional[str] = None,
                expected_output: Optional[str] = None,
            ) -> str:
                """Invent and run a new specialist agent.

                Args:
                    role: Short name for the spawned agent (e.g. 'researcher', 'fact_checker').
                    instructions: Task-specific instructions the spawned agent should follow.
                    input: The concrete task to run.
                    tools: Subset of allowed tool names to give this agent. Omit for no tools.
                    model_tier: Model tier label for this agent's model.
                    expected_output: Optional hint on the desired output format.

                Returns:
                    A short summary of the spawned agent's output. The full output is stored
                    in the workflow's executed_steps trail.
                """
                return self._do_spawn_sync(
                    state,
                    role=role,
                    instructions=instructions,
                    input=input,
                    tools=tools,
                    model_tier=model_tier,
                    expected_output=expected_output,
                )

            return spawn_agent

        def spawn_agent(
            role: str,
            instructions: str,
            input: str,
            tools: Optional[List[str]] = None,
            expected_output: Optional[str] = None,
        ) -> str:
            """Invent and run a new specialist agent.

            Args:
                role: Short name for the spawned agent (e.g. 'researcher', 'fact_checker').
                instructions: Task-specific instructions the spawned agent should follow.
                input: The concrete task to run.
                tools: Subset of allowed tool names to give this agent. Omit for no tools.
                expected_output: Optional hint on the desired output format.

            Returns:
                A short summary of the spawned agent's output. The full output is stored
                in the workflow's executed_steps trail.
            """
            return self._do_spawn_sync(
                state,
                role=role,
                instructions=instructions,
                input=input,
                tools=tools,
                expected_output=expected_output,
            )

        return spawn_agent

    def _build_spawn_tool_async(self, state: _SpawnState) -> Callable:
        if self.allow_model_tier_selection and self.model_tiers:

            async def spawn_agent(
                role: str,
                instructions: str,
                input: str,
                tools: Optional[List[str]] = None,
                model_tier: Optional[str] = None,
                expected_output: Optional[str] = None,
            ) -> str:
                """Invent and run a new specialist agent (async).

                Args:
                    role: Short name for the spawned agent (e.g. 'researcher', 'fact_checker').
                    instructions: Task-specific instructions the spawned agent should follow.
                    input: The concrete task to run.
                    tools: Subset of allowed tool names to give this agent. Omit for no tools.
                    model_tier: Model tier label for this agent's model.
                    expected_output: Optional hint on the desired output format.

                Returns:
                    A short summary of the spawned agent's output.
                """
                return await self._do_spawn_async(
                    state,
                    role=role,
                    instructions=instructions,
                    input=input,
                    tools=tools,
                    model_tier=model_tier,
                    expected_output=expected_output,
                )

            return spawn_agent

        async def spawn_agent(
            role: str,
            instructions: str,
            input: str,
            tools: Optional[List[str]] = None,
            expected_output: Optional[str] = None,
        ) -> str:
            """Invent and run a new specialist agent (async).

            Args:
                role: Short name for the spawned agent (e.g. 'researcher', 'fact_checker').
                instructions: Task-specific instructions the spawned agent should follow.
                input: The concrete task to run.
                tools: Subset of allowed tool names to give this agent. Omit for no tools.
                expected_output: Optional hint on the desired output format.

            Returns:
                A short summary of the spawned agent's output.
            """
            return await self._do_spawn_async(
                state,
                role=role,
                instructions=instructions,
                input=input,
                tools=tools,
                expected_output=expected_output,
            )

        return spawn_agent

    def _input_string(self, execution_input: Optional["WorkflowExecutionInput"]) -> str:
        if execution_input is None or execution_input.input is None:
            return ""
        v = execution_input.input
        if isinstance(v, str):
            return v
        try:
            return str(v)
        except Exception:
            return ""

    def _build_state(
        self,
        workflow: Any,
        execution_input: "WorkflowExecutionInput",
        kwargs: Dict[str, Any],
    ) -> _SpawnState:
        """Populate a _SpawnState with the workflow execution context.

        Pulls workflow_run_response, run_context, workflow_session, and the various
        store_executor_outputs/history/dependency knobs out of kwargs (forwarded from
        Workflow._execute via _call_custom_function) plus from the workflow instance.
        """
        wrr = kwargs.get("workflow_run_response", None)

        # Workflow-level defaults (mirroring how the static path threads these into Step.execute)
        store_executor_outputs = (
            workflow.store_executor_outputs
            if workflow is not None and hasattr(workflow, "store_executor_outputs")
            else True
        )
        add_workflow_history_to_steps = (
            workflow.add_workflow_history_to_steps
            if workflow is not None and getattr(workflow, "add_workflow_history_to_steps", False)
            else None
        )
        num_history_runs = (
            workflow.num_history_runs
            if workflow is not None and hasattr(workflow, "num_history_runs")
            else 3
        )

        return _SpawnState(
            workflow=workflow,
            workflow_run_response=wrr,
            run_context=kwargs.get("run_context"),
            workflow_session=kwargs.get("workflow_session"),
            execution_input=execution_input,
            session_id=wrr.session_id if wrr is not None else None,
            user_id=workflow.user_id if workflow is not None and hasattr(workflow, "user_id") else None,
            store_executor_outputs=store_executor_outputs,
            add_workflow_history_to_steps=add_workflow_history_to_steps,
            num_history_runs=num_history_runs,
            background_tasks=kwargs.get("background_tasks"),
            add_dependencies_to_context=kwargs.get("add_dependencies_to_context"),
            add_session_state_to_context=kwargs.get("add_session_state_to_context"),
        )

    def __call__(self, workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any) -> str:
        """Run the dynamic driver. This makes a DynamicWorkflowDriver usable directly as
        `Workflow(steps=driver)`.

        - If `custom_driver` is set: runs the user's Python function with a `spawn` callable.
        - Otherwise: runs an LLM agent with the `spawn_agent` tool. The driver iterates
          (reasoning + spawning) until it produces a final response.

        Each spawn routes through Step.execute, so it inherits the static-path infrastructure:
        StepStarted/Completed events, full RunOutput persistence (step_executor_runs), retries,
        error policy, media flow, and workflow-history wiring.
        """
        state = self._build_state(workflow, execution_input, kwargs)
        workflow_run_response = state.workflow_run_response

        initial_input = self._input_string(execution_input)

        if self.custom_driver is not None:
            spawn = self._build_spawn_callable_sync(state)
            try:
                result_content = self.custom_driver(initial_input, spawn)
            finally:
                if workflow_run_response is not None:
                    workflow_run_response.executed_steps = list(state.executed_steps)
            if result_content is None:
                return ""
            return result_content if isinstance(result_content, str) else str(result_content)

        spawn_tool = self._build_spawn_tool_sync(state)
        driver_agent = Agent(
            name=self.name,
            model=self.model,
            instructions=self._build_instructions(),
            tools=[spawn_tool],
            db=None,
            telemetry=False,
            num_history_runs=0,
        )

        try:
            result = driver_agent.run(input=initial_input)
        finally:
            if workflow_run_response is not None:
                workflow_run_response.executed_steps = list(state.executed_steps)

        content = result.content if result else ""
        return content if isinstance(content, str) else (str(content) if content is not None else "")

    def stream_call(
        self,
        workflow: Any,
        execution_input: "WorkflowExecutionInput",
        *,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        **kwargs: Any,
    ):
        """Generator variant of __call__ that yields workflow events in real time.

        Runs the driver on a background thread. Per-spawn events from
        Step.execute_stream plus StepSpawnedEvents are pushed into a thread-safe queue;
        this generator yields them in order until the driver completes.

        On completion, the workflow_run_response is populated with executed_steps and
        content (so the workflow's outer stream loop can finalize normally).
        """
        import queue
        import threading

        state = self._build_state(workflow, execution_input, kwargs)
        state.stream_events = stream_events
        state.stream_executor_events = stream_executor_events
        events_q: "queue.Queue[Any]" = queue.Queue()
        _SENTINEL = object()
        state.event_sink = lambda ev: events_q.put(ev)

        workflow_run_response = state.workflow_run_response
        initial_input = self._input_string(execution_input)

        result_container: List[str] = [""]
        error_container: List[Optional[BaseException]] = [None]

        def _runner() -> None:
            try:
                if self.custom_driver is not None:
                    spawn = self._build_spawn_callable_sync(state)
                    out = self.custom_driver(initial_input, spawn)
                    result_container[0] = out if isinstance(out, str) else (str(out) if out is not None else "")
                else:
                    spawn_tool = self._build_spawn_tool_sync(state)
                    driver_agent = Agent(
                        name=self.name,
                        model=self.model,
                        instructions=self._build_instructions(),
                        tools=[spawn_tool],
                        db=None,
                        telemetry=False,
                        num_history_runs=0,
                    )
                    res = driver_agent.run(input=initial_input)
                    content = res.content if res else ""
                    result_container[0] = (
                        content if isinstance(content, str) else (str(content) if content is not None else "")
                    )
            except BaseException as e:
                error_container[0] = e
            finally:
                events_q.put(_SENTINEL)

        thread = threading.Thread(target=_runner, name=f"dyn-driver-{self.name}", daemon=True)
        thread.start()

        try:
            while True:
                item = events_q.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            thread.join()

        if workflow_run_response is not None:
            workflow_run_response.executed_steps = list(state.executed_steps)
            workflow_run_response.content = result_container[0]

        if error_container[0] is not None:
            raise error_container[0]

    def _build_spawn_callable_sync(self, state: _SpawnState) -> Callable:
        """Build a plain-Python spawn callable for use by a custom_driver function."""

        def spawn(
            role: str,
            instructions: str,
            input: str,
            tools: Optional[List[str]] = None,
            model_tier: Optional[str] = None,
            expected_output: Optional[str] = None,
        ) -> str:
            return self._do_spawn_sync(
                state,
                role=role,
                instructions=instructions,
                input=input,
                tools=tools,
                model_tier=model_tier,
                expected_output=expected_output,
            )

        return spawn

    def as_async_workflow_function(self) -> Callable:
        """Return an async function suitable for `Workflow(steps=...)` in async runs.

        Most users should just pass the driver directly: `Workflow(steps=driver)`. The
        synchronous `__call__` handles both `wf.run()` and `wf.arun()` correctly. Use
        this only if you specifically want the driver-internal spawns to run on the
        async path (await agent.arun() per spawn) inside an async workflow.
        """

        async def _driver_fn(workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any) -> str:
            state = self._build_state(workflow, execution_input, kwargs)
            workflow_run_response = state.workflow_run_response

            spawn_tool = self._build_spawn_tool_async(state)

            driver_agent = Agent(
                name=self.name,
                model=self.model,
                instructions=self._build_instructions(),
                tools=[spawn_tool],
                db=None,
                telemetry=False,
                num_history_runs=0,
            )

            initial_input = self._input_string(execution_input)
            try:
                result = await driver_agent.arun(input=initial_input)
            finally:
                if workflow_run_response is not None:
                    workflow_run_response.executed_steps = list(state.executed_steps)

            content = result.content if result else ""
            return content if isinstance(content, str) else (str(content) if content is not None else "")

        _driver_fn.__name__ = f"dynamic_workflow_driver_async[{self.name}]"
        return _driver_fn
