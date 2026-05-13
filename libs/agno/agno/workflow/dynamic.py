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

if TYPE_CHECKING:
    from agno.run.workflow import WorkflowRunOutput
    from agno.workflow.types import WorkflowExecutionInput


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
    """Mutable state shared between the driver function and the spawn tool closure."""

    trail_outputs: List[Any] = field(default_factory=list)
    executed_steps: List[ExecutedStepRecord] = field(default_factory=list)
    iteration: int = 0
    spawn_count: int = 0
    workflow_run_response: Optional["WorkflowRunOutput"] = None


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

        agent_input = input if not expected_output else f"{input}\n\nExpected output: {expected_output}"
        try:
            result = agent.run(input=agent_input)
        except Exception as e:
            log_warning(f"DynamicWorkflowDriver spawn '{role}' failed: {e}")
            return f"Error running spawned agent '{role}': {e}"

        content = result.content if result else ""
        content_str = content if isinstance(content, str) else str(content) if content is not None else ""

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
            step_id=str(uuid4()),
        )
        state.executed_steps.append(record)
        state.trail_outputs.append(content_str)

        # Also reflect into workflow_run_response.step_results for ecosystem compatibility
        if state.workflow_run_response is not None:
            try:
                from agno.workflow.types import StepOutput

                state.workflow_run_response.step_results.append(
                    StepOutput(step_name=role, step_id=record.step_id, content=content_str)
                )
            except Exception as e:
                log_debug(f"DynamicWorkflowDriver: could not append StepOutput to step_results: {e}")

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

        agent_input = input if not expected_output else f"{input}\n\nExpected output: {expected_output}"
        try:
            result = await agent.arun(input=agent_input)
        except Exception as e:
            log_warning(f"DynamicWorkflowDriver spawn '{role}' failed: {e}")
            return f"Error running spawned agent '{role}': {e}"

        content = result.content if result else ""
        content_str = content if isinstance(content, str) else str(content) if content is not None else ""

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
            step_id=str(uuid4()),
        )
        state.executed_steps.append(record)
        state.trail_outputs.append(content_str)

        if state.workflow_run_response is not None:
            try:
                from agno.workflow.types import StepOutput

                state.workflow_run_response.step_results.append(
                    StepOutput(step_name=role, step_id=record.step_id, content=content_str)
                )
            except Exception as e:
                log_debug(f"DynamicWorkflowDriver: could not append StepOutput to step_results: {e}")

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
        if state.workflow_run_response is None:
            return
        try:
            from agno.run.workflow import StepSpawnedEvent

            event = StepSpawnedEvent(
                iteration=iteration,
                role=role,
                instructions=instructions[:200],
                input=input[:200],
                tool_names=tools or None,
                model_tier=model_tier,
                run_id=state.workflow_run_response.run_id,
                session_id=state.workflow_run_response.session_id,
                workflow_id=state.workflow_run_response.workflow_id,
                workflow_name=state.workflow_run_response.workflow_name,
            )
            if state.workflow_run_response.events is None:
                state.workflow_run_response.events = []
            state.workflow_run_response.events.append(event)
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

    def __call__(self, workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any) -> str:
        """Run the dynamic driver. This makes a DynamicWorkflowDriver usable directly as
        `Workflow(steps=driver)`.

        - If `custom_driver` is set: runs the user's Python function with a `spawn` callable.
        - Otherwise: runs an LLM agent with the `spawn_agent` tool. The driver iterates
          (reasoning + spawning) until it produces a final response.

        Either way, the workflow's run output is populated with executed_steps and step_results.
        """
        workflow_run_response = kwargs.get("workflow_run_response", None)
        state = _SpawnState(workflow_run_response=workflow_run_response)

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
            workflow_run_response = kwargs.get("workflow_run_response", None)
            state = _SpawnState(workflow_run_response=workflow_run_response)

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
