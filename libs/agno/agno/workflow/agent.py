"""WorkflowAgent - A restricted Agent for workflow orchestration"""

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from agno.agent import Agent
from agno.models.base import Model
from agno.utils.log import log_debug, log_info, logger

if TYPE_CHECKING:
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
    ):
        """
        Initialize WorkflowAgent with restricted parameters.
        Args:
            model: The model to use for the agent (required)
            name: Agent name (defaults to "Workflow Agent")
            description: Agent description
            instructions: Custom instructions (will be combined with workflow context)
        """

        default_instructions = """You are a workflow orchestration agent. Your job is to help users by either:
            1. **Answering directly** from the workflow history context if the question can be answered from previous runs
            2. **Running the workflow** by calling the run_workflow tool ONCE when you need to process a new query

            Guidelines:
            - Check the workflow history first to see if the answer already exists
            - If the user asks about something that was already processed, answer directly from history
            - If the user asks a new question that requires workflow execution, call the run_workflow tool ONCE
            - After calling the tool, the result will be returned to you - use that result to answer the user
            - IMPORTANT: Do NOT call the tool multiple times. Call it once and use the result.
            - Keep your responses concise and helpful
            - When calling the workflow, pass a clear and concise query

            {workflow_context}
        """

        super().__init__(
            model=model,
            instructions=instructions or default_instructions,
            resolve_in_context=True,
        )

    def create_workflow_tool(
        self,
        workflow: "Any",  # Workflow type
        session: "WorkflowSession",
        execution_input: "WorkflowExecutionInput",
        session_state: Optional[Dict[str, Any]],
        stream_intermediate_steps: bool = False,
    ) -> Callable:
        """
        Create the workflow execution tool that this agent can call.
        This is similar to how Agent has search_knowledge_base() method.
        Args:
            workflow: The workflow instance
            session: The workflow session
            execution_input: The execution input
            session_state: The session state
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
            fresh_session = workflow.get_session(session_id=session.session_id)
            if fresh_session is None:
                fresh_session = session  # Fallback to closure session if reload fails
                log_info(
                    f"Fallback to closure session: {len(fresh_session.workflow_agent_responses or [])} agent responses"
                )
            else:
                log_info(
                    f"Reloaded session before tool execution: {len(fresh_session.workflow_agent_responses or [])} agent responses"
                )

            # Create a new run ID for this execution
            run_id = str(uuid4())
            log_debug(f"Created new run ID: {run_id}")

            # Create workflow run response
            workflow_run_response = WorkflowRunOutput(
                run_id=run_id,
                input=query,
                session_id=fresh_session.session_id,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                created_at=int(datetime.now().timestamp()),
            )

            # Update the execution input with the agent's refined query
            workflow_execution_input = WorkflowExecutionInput(
                input=query,
                additional_data=execution_input.additional_data,
                audio=execution_input.audio,
                images=execution_input.images,
                videos=execution_input.videos,
                files=execution_input.files,
            )

            # ===== EXECUTION LOGIC (Based on streaming mode) =====
            if stream_intermediate_steps:
                # STREAMING MODE: Yield workflow events
                log_debug("Executing workflow with streaming...")

                final_content = ""
                for event in workflow._execute_stream(
                    session=fresh_session,
                    execution_input=workflow_execution_input,
                    workflow_run_response=workflow_run_response,
                    session_state=session_state,
                    stream_intermediate_steps=True,
                ):
                    yield event

                    # Capture final content from WorkflowCompletedEvent
                    from agno.run.workflow import WorkflowCompletedEvent

                    if isinstance(event, WorkflowCompletedEvent):
                        final_content = str(event.content) if event.content else ""

                logger.info("=" * 80)
                logger.info(f"TOOL EXECUTION COMPLETE: run_workflow")
                logger.info("=" * 80)

                return final_content
            else:
                # NON-STREAMING MODE: Execute synchronously
                log_debug("Executing workflow steps...")

                result = workflow._execute(
                    session=fresh_session,
                    execution_input=workflow_execution_input,
                    workflow_run_response=workflow_run_response,
                    session_state=session_state,
                )

                logger.info("=" * 80)
                logger.info(f"TOOL EXECUTION COMPLETE: run_workflow")
                logger.info(f"  ➜ Run ID: {result.run_id}")
                logger.info(f"  ➜ Result length: {len(str(result.content)) if result.content else 0} chars")
                logger.info("=" * 80)

                # Return the content as string
                if isinstance(result.content, str):
                    return result.content
                elif isinstance(result.content, BaseModel):
                    return result.content.model_dump_json(exclude_none=True)
                else:
                    return str(result.content)

        return run_workflow
