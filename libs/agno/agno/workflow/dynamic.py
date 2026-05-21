"""_DynamicSpawnEngine - the runtime engine behind a dynamic-mode WorkflowAgent.

A dynamic workflow expands itself at runtime: instead of declaring a static list of
steps, the user hands a dynamic-mode `WorkflowAgent` to `Workflow(agent=...)`. The
agent's LLM invents new specialist agents on demand by calling spawn tools (currently:
`spawn_agent`). Each spawn creates an ephemeral Agent with the role/instructions/tools
the LLM chose, runs it through Step.execute(_stream), and returns a short summary back
so the orchestrator's context stays clean across many spawns.

This module holds the engine (`_DynamicSpawnEngine`); `WorkflowAgent` composes one when
its spawn-policy fields are set and delegates __call__ / stream_call /
as_async_workflow_function to it. The engine is NOT public — use WorkflowAgent.

The output of `Workflow.run(...)` carries:
- `content`: the orchestrator's final response after all spawns
- `executed_steps`: the canonical leaf trail (one ExecutedStepRecord per agent spawn,
  with parent_id for spawns nested inside composites)
- `step_results`: the same trail re-expressed as StepOutput objects in the static
  workflow shape — composite spawns (Loop/Parallel/Router, v0.1+) nest their children
  under `StepOutput.steps`
- `step_executor_runs`: full RunOutput per spawned agent when store_executor_outputs=True

Each spawn type is implemented as a _SpawnHandler in agno.workflow.dynamic_handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from agno.agent import Agent
from agno.models.base import Model
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_warning
from agno.workflow.dynamic_handlers import (
    _AgentSpawnHandler,
    _MaxStepsExceededError,
    _RunContext,
    _StreamBridge,
    _TrailBuilder,
)

if TYPE_CHECKING:
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


def _max_steps_msg(max_steps: int) -> str:
    return (
        f"max_steps ({max_steps}) reached. No more agents may be spawned. "
        "Produce your final response now based on the spawns so far."
    )


class _DynamicSpawnEngine:
    """Runtime engine behind a dynamic-mode WorkflowAgent. Not public.

    Holds spawn policy + the per-run plumbing and exposes the three workflow entry
    shapes (__call__, stream_call, as_async_workflow_function). WorkflowAgent composes
    one and delegates to it.
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
        name: str = "workflow_agent",
        custom_driver: Optional[Callable[[str, Callable], str]] = None,
    ):
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

        # The leaf handler — future composite handlers (Parallel, Loop, ...) will compose this.
        self._agent_handler = _AgentSpawnHandler(
            model=self.model,
            allowed_tools=self.allowed_tools,
            allow_tool_selection=self.allow_tool_selection,
            model_tiers=self.model_tiers,
            allow_model_tier_selection=self.allow_model_tier_selection,
            step_summary_max_chars=self.step_summary_max_chars,
            show_step_output=self.show_step_output,
            log_step_runs=self.log_step_runs,
        )

    # ---- driver-agent instructions -----------------------------------------

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

    # ---- run context construction ------------------------------------------

    def _build_ctx_trail(
        self,
        workflow: Any,
        execution_input: "WorkflowExecutionInput",
        kwargs: Dict[str, Any],
    ) -> "tuple[_RunContext, _TrailBuilder]":
        """Build (_RunContext, _TrailBuilder) from the workflow's kwargs.

        _StreamBridge is built separately by the caller because streaming wires up
        an event_sink.
        """
        wrr = kwargs.get("workflow_run_response", None)

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
            workflow.num_history_runs if workflow is not None and hasattr(workflow, "num_history_runs") else 3
        )

        ctx = _RunContext(
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
        trail = _TrailBuilder(max_steps=self.max_steps)
        return ctx, trail

    @staticmethod
    def _input_string(execution_input: Optional["WorkflowExecutionInput"]) -> str:
        if execution_input is None or execution_input.input is None:
            return ""
        v = execution_input.input
        if isinstance(v, str):
            return v
        try:
            return str(v)
        except Exception:
            return ""

    @staticmethod
    def _finalize(ctx: _RunContext, trail: _TrailBuilder) -> None:
        """Promote the trail onto the workflow run response."""
        if ctx.workflow_run_response is not None:
            ctx.workflow_run_response.executed_steps = list(trail.leaf_records)

    # ---- spawn tools (LLM-facing) ------------------------------------------

    def _build_spawn_agent_tool(self, ctx: _RunContext, trail: _TrailBuilder, stream: _StreamBridge) -> Callable:
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
                    role: Short name for the spawned agent (e.g. 'researcher').
                    instructions: Task-specific instructions for the spawned agent.
                    input: The concrete task to run.
                    tools: Subset of allowed tool names to give this agent.
                    model_tier: Model tier label for this agent's model.
                    expected_output: Optional hint on the desired output format.

                Returns:
                    A short summary of the spawned agent's output.
                """
                try:
                    node = self._agent_handler.spawn(
                        ctx,
                        trail,
                        stream,
                        role=role,
                        instructions=instructions,
                        input=input,
                        tools=tools,
                        model_tier=model_tier,
                        expected_output=expected_output,
                    )
                except _MaxStepsExceededError as e:
                    msg = _max_steps_msg(e.max_steps)
                    log_warning(f"WorkflowAgent: {msg}")
                    return msg
                except Exception as e:
                    log_warning(f"WorkflowAgent spawn {role!r} failed: {e}")
                    return f"Error running spawned agent {role!r}: {e}"

                return self._agent_handler.summary_for_tool_result(node.output)

            return spawn_agent

        def spawn_agent(  # type: ignore[no-redef]
            role: str,
            instructions: str,
            input: str,
            tools: Optional[List[str]] = None,
            expected_output: Optional[str] = None,
        ) -> str:
            """Invent and run a new specialist agent.

            Args:
                role: Short name for the spawned agent (e.g. 'researcher').
                instructions: Task-specific instructions for the spawned agent.
                input: The concrete task to run.
                tools: Subset of allowed tool names to give this agent.
                expected_output: Optional hint on the desired output format.

            Returns:
                A short summary of the spawned agent's output.
            """
            try:
                node = self._agent_handler.spawn(
                    ctx,
                    trail,
                    stream,
                    role=role,
                    instructions=instructions,
                    input=input,
                    tools=tools,
                    expected_output=expected_output,
                )
            except _MaxStepsExceededError as e:
                msg = _max_steps_msg(e.max_steps)
                log_warning(f"WorkflowAgent: {msg}")
                return msg
            except Exception as e:
                log_warning(f"WorkflowAgent spawn {role!r} failed: {e}")
                return f"Error running spawned agent {role!r}: {e}"

            return self._agent_handler.summary_for_tool_result(node.output)

        return spawn_agent

    def _build_spawn_agent_tool_async(self, ctx: _RunContext, trail: _TrailBuilder, stream: _StreamBridge) -> Callable:
        if self.allow_model_tier_selection and self.model_tiers:

            async def spawn_agent(
                role: str,
                instructions: str,
                input: str,
                tools: Optional[List[str]] = None,
                model_tier: Optional[str] = None,
                expected_output: Optional[str] = None,
            ) -> str:
                """Invent and run a new specialist agent (async)."""
                try:
                    node = await self._agent_handler.aspawn(
                        ctx,
                        trail,
                        stream,
                        role=role,
                        instructions=instructions,
                        input=input,
                        tools=tools,
                        model_tier=model_tier,
                        expected_output=expected_output,
                    )
                except _MaxStepsExceededError as e:
                    msg = _max_steps_msg(e.max_steps)
                    log_warning(f"WorkflowAgent: {msg}")
                    return msg
                except Exception as e:
                    log_warning(f"WorkflowAgent spawn {role!r} failed: {e}")
                    return f"Error running spawned agent {role!r}: {e}"

                return self._agent_handler.summary_for_tool_result(node.output)

            return spawn_agent

        async def spawn_agent(  # type: ignore[no-redef]
            role: str,
            instructions: str,
            input: str,
            tools: Optional[List[str]] = None,
            expected_output: Optional[str] = None,
        ) -> str:
            """Invent and run a new specialist agent (async)."""
            try:
                node = await self._agent_handler.aspawn(
                    ctx,
                    trail,
                    stream,
                    role=role,
                    instructions=instructions,
                    input=input,
                    tools=tools,
                    expected_output=expected_output,
                )
            except _MaxStepsExceededError as e:
                msg = _max_steps_msg(e.max_steps)
                log_warning(f"WorkflowAgent: {msg}")
                return msg
            except Exception as e:
                log_warning(f"WorkflowAgent spawn {role!r} failed: {e}")
                return f"Error running spawned agent {role!r}: {e}"

            return self._agent_handler.summary_for_tool_result(node.output)

        return spawn_agent

    # ---- python-driver mode (the user-callable spawn) ----------------------

    def _build_python_spawn(self, ctx: _RunContext, trail: _TrailBuilder, stream: _StreamBridge) -> Callable:
        """Build the spawn callable a custom_driver function receives.

        Matches the LLM-facing tool's signature but raises on max_steps rather than
        returning an error string (Python drivers want exceptions, not magic strings).
        """

        def spawn(
            role: str,
            instructions: str,
            input: str,
            tools: Optional[List[str]] = None,
            model_tier: Optional[str] = None,
            expected_output: Optional[str] = None,
        ) -> str:
            node = self._agent_handler.spawn(
                ctx,
                trail,
                stream,
                role=role,
                instructions=instructions,
                input=input,
                tools=tools,
                model_tier=model_tier,
                expected_output=expected_output,
            )
            content = node.output.content if node.output is not None else ""
            return content if isinstance(content, str) else (str(content) if content is not None else "")

        return spawn

    # ---- entry points (non-streaming) --------------------------------------

    def __call__(self, workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any) -> str:
        """Non-streaming entry point — `Workflow(steps=driver)` calls this."""
        ctx, trail = self._build_ctx_trail(workflow, execution_input, kwargs)
        stream = _StreamBridge()  # inactive — no event_sink
        initial_input = self._input_string(execution_input)

        if self.custom_driver is not None:
            spawn = self._build_python_spawn(ctx, trail, stream)
            try:
                result_content = self.custom_driver(initial_input, spawn)
            finally:
                self._finalize(ctx, trail)
            if result_content is None:
                return ""
            return result_content if isinstance(result_content, str) else str(result_content)

        spawn_tool = self._build_spawn_agent_tool(ctx, trail, stream)
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
            self._finalize(ctx, trail)

        content = result.content if result else ""
        return content if isinstance(content, str) else (str(content) if content is not None else "")

    # ---- entry points (streaming) ------------------------------------------

    def stream_call(
        self,
        workflow: Any,
        execution_input: "WorkflowExecutionInput",
        *,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        **kwargs: Any,
    ):
        """Generator variant of __call__ — yields workflow events in real time.

        Driver runs on a background thread. Step.execute_stream emits per-spawn events
        which the agent handler pushes into the stream bridge's queue. This generator
        yields them in order until the driver completes. On completion the
        workflow_run_response gets `content` and `executed_steps` populated so the
        workflow's outer stream loop finalizes normally.
        """
        import queue
        import threading

        ctx, trail = self._build_ctx_trail(workflow, execution_input, kwargs)
        events_q: "queue.Queue[Any]" = queue.Queue()
        _SENTINEL = object()
        stream = _StreamBridge(
            event_sink=lambda ev: events_q.put(ev),
            stream_events=stream_events,
            stream_executor_events=stream_executor_events,
        )

        initial_input = self._input_string(execution_input)
        result_container: List[str] = [""]
        error_container: List[Optional[BaseException]] = [None]

        def _runner() -> None:
            try:
                if self.custom_driver is not None:
                    spawn = self._build_python_spawn(ctx, trail, stream)
                    out = self.custom_driver(initial_input, spawn)
                    result_container[0] = out if isinstance(out, str) else (str(out) if out is not None else "")
                else:
                    spawn_tool = self._build_spawn_agent_tool(ctx, trail, stream)
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

        self._finalize(ctx, trail)
        if ctx.workflow_run_response is not None:
            ctx.workflow_run_response.content = result_container[0]

        if error_container[0] is not None:
            raise error_container[0]

    # ---- async helper (kept for users who explicitly need async spawns) ----

    def as_async_workflow_function(self) -> Callable:
        """Return an async function suitable for `Workflow(steps=...)` in async runs.

        Most users should just pass the driver directly: `Workflow(steps=driver)`. The
        synchronous `__call__` handles both `wf.run()` and `wf.arun()`. Use this only
        if you specifically want each spawn to run via `await agent.arun()`.
        """

        async def _driver_fn(workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any) -> str:
            ctx, trail = self._build_ctx_trail(workflow, execution_input, kwargs)
            stream = _StreamBridge()
            initial_input = self._input_string(execution_input)

            if self.custom_driver is not None:
                # Python custom driver is sync; spawns run via the sync Step.execute path.
                spawn = self._build_python_spawn(ctx, trail, stream)
                try:
                    result_content = self.custom_driver(initial_input, spawn)
                finally:
                    self._finalize(ctx, trail)
                if result_content is None:
                    return ""
                return result_content if isinstance(result_content, str) else str(result_content)

            spawn_tool = self._build_spawn_agent_tool_async(ctx, trail, stream)
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
                result = await driver_agent.arun(input=initial_input)
            finally:
                self._finalize(ctx, trail)

            content = result.content if result else ""
            return content if isinstance(content, str) else (str(content) if content is not None else "")

        _driver_fn.__name__ = f"workflow_agent_async[{self.name}]"
        return _driver_fn
