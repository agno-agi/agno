"""WorkflowAgent - A restricted Agent for workflow orchestration"""

from typing import TYPE_CHECKING, Any, Callable, Optional

from agno.agent import Agent
from agno.models.base import Model
from agno.run import RunContext

if TYPE_CHECKING:
    from agno.os.managers import WebSocketHandler
    from agno.session.workflow import WorkflowSession
    from agno.workflow.types import WorkflowExecutionInput


class WorkflowAgent(Agent):
    """
    A restricted Agent class specifically designed for workflow orchestration.
    This agent can:
    1. Decide whether to run the workflow or answer directly from history
    2. Call the workflow execution tool when needed
    3. Access workflow session history for context
    Restrictions:
    - Only model configuration allowed
    - No custom tools (tools are set by workflow)
    - No knowledge base
    - Limited configuration options
    """

    def __init__(
        self,
        model: Model,
        instructions: Optional[str] = None,
        add_workflow_history: bool = True,
        num_history_runs: int = 5,
    ):
        """
        Initialize WorkflowAgent with restricted parameters.
        Args:
            model: The model to use for the agent (required)
            instructions: Custom instructions (will be combined with workflow context)
            add_workflow_history: Whether to add workflow history to context (default: True)
            num_history_runs: Number of previous workflow runs to include in context (default: 5)
        """
        self.add_workflow_history = add_workflow_history

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
