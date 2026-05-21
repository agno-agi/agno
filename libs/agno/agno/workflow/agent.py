"""WorkflowAgent - the agent that drives a workflow.

Two modes, selected implicitly from the constructor args:

1. **Gate mode** (default). Given a user message, decide whether to *run the workflow's
   static steps* (via the `run_workflow` tool) or answer directly from history. Used as
   `Workflow(agent=WorkflowAgent(model=...), steps=[...])`.

2. **Dynamic mode** (when any spawn-policy arg is set: `allowed_tools`, `custom_driver`,
   `model_tiers`, or a non-default `max_steps`). The agent IS the workflow body — it
   invents specialist agents at runtime via a `spawn_agent` tool. Used as
   `Workflow(agent=WorkflowAgent(model=..., allowed_tools=[...]))` with no `steps`.
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from agno.agent import Agent
from agno.models.base import Model
from agno.run import RunContext
from agno.tools import Toolkit
from agno.tools.function import Function

if TYPE_CHECKING:
    from agno.os.managers import WebSocketHandler
    from agno.session.workflow import WorkflowSession
    from agno.workflow.types import WorkflowExecutionInput

# Sentinel so we can tell "user passed max_steps" from "default", which decides dynamic mode.
_DEFAULT_MAX_STEPS = 10


class WorkflowAgent(Agent):
    """
    The agent that drives a workflow. Operates in one of two modes (see module docstring):
    gate mode (decide run-vs-answer over static steps) or dynamic mode (spawn specialists
    at runtime as the workflow body).
    """

    def __init__(
        self,
        model: Optional[Model] = None,
        instructions: Optional[str] = None,
        add_workflow_history: bool = True,
        num_history_runs: int = 5,
        # --- Dynamic-mode (spawn) policy. Presence of any of these => dynamic mode. ---
        allowed_tools: Optional[List[Union[Toolkit, Callable, Function]]] = None,
        allow_tool_selection: bool = True,
        model_tiers: Optional[Dict[str, str]] = None,
        allow_model_tier_selection: bool = False,
        tier_hints: Optional[Dict[str, str]] = None,
        max_steps: int = _DEFAULT_MAX_STEPS,
        step_summary_max_chars: int = 1200,
        show_step_output: bool = False,
        log_step_runs: bool = True,
        custom_driver: Optional[Callable[[str, Callable], str]] = None,
    ):
        """
        Args:
            model: The model to use (required unless `custom_driver` is set in dynamic mode).
            instructions: Custom instructions. In gate mode they're combined with workflow
                context; in dynamic mode they describe the orchestration goal.
            add_workflow_history: (gate mode) add workflow history to context.
            num_history_runs: (gate mode) previous workflow runs to include in context.
            allowed_tools: (dynamic) tools spawned agents may use. Setting this => dynamic mode.
            allow_tool_selection: (dynamic) let the LLM pick a tool subset per spawn.
            model_tiers: (dynamic) label -> model id, for cost-aware per-spawn model choice.
            allow_model_tier_selection: (dynamic) expose model_tier to the LLM per spawn.
            tier_hints: (dynamic) guidance shown alongside tier labels.
            max_steps: (dynamic) cap on total spawns. A non-default value => dynamic mode.
            step_summary_max_chars: (dynamic) cap on the spawn output returned to the driver.
            show_step_output: (dynamic) print each spawned agent's full output.
            log_step_runs: (dynamic) emit a log line per spawn.
            custom_driver: (dynamic) a Python `(workflow_input, spawn) -> str` driver instead
                of the LLM. Setting this => dynamic mode.
        """
        # Decide mode from the spawn-policy args.
        self._is_dynamic = (
            allowed_tools is not None
            or custom_driver is not None
            or model_tiers is not None
            or max_steps != _DEFAULT_MAX_STEPS
        )

        if self._is_dynamic:
            if custom_driver is None and model is None:
                raise ValueError(
                    "Dynamic-mode WorkflowAgent requires either `model=` (LLM-driven) "
                    "or `custom_driver=` (Python-driven)."
                )
            self.add_workflow_history = add_workflow_history
            self._dynamic_engine = self._build_dynamic_engine(
                model=model,
                instructions=instructions,
                allowed_tools=allowed_tools,
                allow_tool_selection=allow_tool_selection,
                model_tiers=model_tiers,
                allow_model_tier_selection=allow_model_tier_selection,
                tier_hints=tier_hints,
                max_steps=max_steps,
                step_summary_max_chars=step_summary_max_chars,
                show_step_output=show_step_output,
                log_step_runs=log_step_runs,
                custom_driver=custom_driver,
            )
            # A dynamic WorkflowAgent still subclasses Agent for type compatibility with
            # Workflow.agent, but its own Agent loop is unused — the engine builds the
            # ephemeral orchestrator agent per run. Initialize a minimal Agent shell.
            super().__init__(model=model, instructions=instructions)
            return

        # ---- Gate mode (unchanged behavior) ----
        self._dynamic_engine = None
        self.add_workflow_history = add_workflow_history

        if model is None:
            raise ValueError("Gate-mode WorkflowAgent requires a `model`.")

        default_instructions = """You are a workflow orchestration agent. Your job is to help users by either:
1. **Answering directly** from the workflow history context if the question can be answered from previous runs
2. **Running the workflow** by calling the run_workflow tool ONCE when you need to process a new query

Guidelines:
- ALWAYS check the workflow history first before calling the tool
- Answer directly from history if:
    * The user asks about something already in history
    * The user asks for comparisons/analysis of things in history (e.g., "compare X and Y")
    * The user asks follow-up questions about previous results
- Only call the run_workflow tool for NEW topics not covered in history
- IMPORTANT: Do NOT call the tool multiple times. Call it once and use the result.
- Keep your responses concise and helpful
- When you must call the workflow, pass a clear and concise query

{workflow_context}
"""

        if instructions:
            if "{workflow_context}" not in instructions:
                # Add the workflow context placeholder
                final_instructions = f"{instructions}\n\n{{workflow_context}}"
            else:
                final_instructions = instructions
        else:
            final_instructions = default_instructions

        super().__init__(
            model=model,
            instructions=final_instructions,
            resolve_in_context=True,
            num_history_runs=num_history_runs,
        )

    # ---- dynamic mode ------------------------------------------------------

    @property
    def is_dynamic(self) -> bool:
        """True when this agent drives a workflow by spawning specialists at runtime."""
        return self._is_dynamic

    def _build_dynamic_engine(self, **kwargs: Any):
        from agno.workflow.dynamic import _DynamicSpawnEngine

        return _DynamicSpawnEngine(name="workflow_agent", **kwargs)

    def __call__(self, workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any) -> str:
        """Dynamic-mode non-streaming entry — delegates to the spawn engine."""
        return self._dynamic_engine(workflow, execution_input, **kwargs)

    def stream_call(self, workflow: Any, execution_input: "WorkflowExecutionInput", **kwargs: Any):
        """Dynamic-mode streaming entry — yields workflow events."""
        return self._dynamic_engine.stream_call(workflow, execution_input, **kwargs)

    def as_async_workflow_function(self) -> Callable:
        """Dynamic-mode async entry — returns an async workflow function."""
        return self._dynamic_engine.as_async_workflow_function()

    def create_workflow_tool(
        self,
        workflow: "Any",  # Workflow type
        session: "WorkflowSession",
        execution_input: "WorkflowExecutionInput",
        run_context: RunContext,
        stream: bool = False,
    ) -> Callable:
        """
        Create the workflow execution tool that this agent can call.
        This is similar to how Agent has search_knowledge_base() method.
        Args:
            workflow: The workflow instance
            session: The workflow session
            execution_input: The execution input
            run_context: The run context
            stream: Whether to stream the workflow execution
        Returns:
            Callable tool function
        """
        from datetime import datetime
        from uuid import uuid4

        from pydantic import BaseModel

        from agno.run.workflow import WorkflowRunOutput
        from agno.utils.log import log_debug
        from agno.workflow.types import WorkflowExecutionInput

        def run_workflow(query: str):
            """
            Execute the complete workflow with the given query.
            Use this tool when you need to run the workflow to answer the user's question.

            Args:
                query: The input query/question to process through the workflow
            Returns:
                The workflow execution result (str in non-streaming, generator in streaming)
            """
            # Reload session to get latest data from database
            # This ensures we don't overwrite any updates made after the tool was created
            session_from_db = workflow.get_session(session_id=session.session_id)
            if session_from_db is None:
                session_from_db = session  # Fallback to closure session if reload fails
                log_debug(f"Fallback to closure session: {len(session_from_db.runs or [])} runs")
            else:
                log_debug(f"Reloaded session before tool execution: {len(session_from_db.runs or [])} runs")

            # Create a new run ID for this execution
            run_id = str(uuid4())

            workflow_run_response = WorkflowRunOutput(
                run_id=run_id,
                input=execution_input.input,  # Use original user input
                session_id=session_from_db.session_id,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                created_at=int(datetime.now().timestamp()),
            )

            workflow_execution_input = WorkflowExecutionInput(
                input=query,  # Agent's refined query for execution
                additional_data=execution_input.additional_data,
                audio=execution_input.audio,
                images=execution_input.images,
                videos=execution_input.videos,
                files=execution_input.files,
            )

            # ===== EXECUTION LOGIC (Based on streaming mode) =====
            if stream:
                final_content = ""
                for event in workflow._execute_stream(
                    session=session_from_db,
                    run_context=run_context,
                    execution_input=workflow_execution_input,
                    workflow_run_response=workflow_run_response,
                    stream_events=True,
                ):
                    yield event

                    # Capture final content from WorkflowCompletedEvent
                    from agno.run.workflow import WorkflowCompletedEvent

                    if isinstance(event, WorkflowCompletedEvent):
                        final_content = str(event.content) if event.content else ""

                return final_content
            else:
                # NON-STREAMING MODE: Execute synchronously
                result = workflow._execute(
                    session=session_from_db,
                    execution_input=workflow_execution_input,
                    workflow_run_response=workflow_run_response,
                    run_context=run_context,
                )

                if isinstance(result.content, str):
                    return result.content
                elif isinstance(result.content, BaseModel):
                    return result.content.model_dump_json(exclude_none=True)
                else:
                    return str(result.content)

        return run_workflow

    def async_create_workflow_tool(
        self,
        workflow: "Any",  # Workflow type
        session: "WorkflowSession",
        execution_input: "WorkflowExecutionInput",
        run_context: RunContext,
        stream: bool = False,
        websocket_handler: Optional["WebSocketHandler"] = None,
    ) -> Callable:
        """
        Create the async workflow execution tool that this agent can call.
        This is the async counterpart of create_workflow_tool.

        Args:
            workflow: The workflow instance
            session: The workflow session
            execution_input: The execution input
            run_context: The run context
            stream: Whether to stream the workflow execution

        Returns:
            Async callable tool function
        """
        from datetime import datetime
        from uuid import uuid4

        from pydantic import BaseModel

        from agno.run.workflow import WorkflowRunOutput
        from agno.utils.log import log_debug
        from agno.workflow.types import WorkflowExecutionInput

        async def run_workflow(query: str):
            """
            Execute the complete workflow with the given query asynchronously.
            Use this tool when you need to run the workflow to answer the user's question.

            Args:
                query: The input query/question to process through the workflow

            Returns:
                The workflow execution result (str in non-streaming, async generator in streaming)
            """
            # Reload session to get latest data from database
            # This ensures we don't overwrite any updates made after the tool was created
            # Use async or sync method based on database type
            if workflow._has_async_db():
                session_from_db = await workflow.aget_session(session_id=session.session_id)
            else:
                session_from_db = workflow.get_session(session_id=session.session_id)

            if session_from_db is None:
                session_from_db = session  # Fallback to closure session if reload fails
                log_debug(f"Fallback to closure session: {len(session_from_db.runs or [])} runs")
            else:
                log_debug(f"Reloaded session before async tool execution: {len(session_from_db.runs or [])} runs")

            # Create a new run ID for this execution
            run_id = str(uuid4())

            workflow_run_response = WorkflowRunOutput(
                run_id=run_id,
                input=execution_input.input,  # Use original user input
                session_id=session_from_db.session_id,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                created_at=int(datetime.now().timestamp()),
            )

            workflow_execution_input = WorkflowExecutionInput(
                input=query,  # Agent's refined query for execution
                additional_data=execution_input.additional_data,
                audio=execution_input.audio,
                images=execution_input.images,
                videos=execution_input.videos,
                files=execution_input.files,
            )

            if stream:
                final_content = ""
                async for event in workflow._aexecute_stream(
                    session_id=session_from_db.session_id,
                    user_id=session_from_db.user_id,
                    execution_input=workflow_execution_input,
                    workflow_run_response=workflow_run_response,
                    run_context=run_context,
                    stream_events=True,
                    websocket_handler=websocket_handler,
                ):
                    yield event

                    from agno.run.workflow import WorkflowCompletedEvent

                    if isinstance(event, WorkflowCompletedEvent):
                        final_content = str(event.content) if event.content else ""

                yield final_content
            else:
                result = await workflow._aexecute(
                    session_id=session_from_db.session_id,
                    user_id=session_from_db.user_id,
                    execution_input=workflow_execution_input,
                    workflow_run_response=workflow_run_response,
                    run_context=run_context,
                )

                if isinstance(result.content, str):
                    yield result.content
                elif isinstance(result.content, BaseModel):
                    yield result.content.model_dump_json(exclude_none=True)
                else:
                    yield str(result.content)

        return run_workflow
