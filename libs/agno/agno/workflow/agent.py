"""WorkflowAgent - A restricted Agent for workflow orchestration"""

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from agno.agent import Agent
from agno.models.base import Model
from agno.utils.log import log_debug, logger

if TYPE_CHECKING:
    from agno.workflow.types import WorkflowExecutionInput
    from agno.session.workflow import WorkflowSession


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
        name: Optional[str] = "Workflow Agent",
        description: Optional[str] = None,
        instructions: Optional[str] = None,
        # Explicitly disable features not needed for workflow agent
        tools: None = None,
        knowledge: None = None,
        db: None = None,
        **kwargs: Any,
    ):
        """
        Initialize WorkflowAgent with restricted parameters.
        
        Args:
            model: The model to use for the agent (required)
            name: Agent name (defaults to "Workflow Agent")
            description: Agent description
            instructions: Custom instructions (will be combined with workflow context)
            **kwargs: Additional arguments - only debug_mode and monitoring are allowed
        
        Raises:
            ValueError: If any disallowed parameters are provided
        """
        
        # Define allowed additional kwargs beyond the core parameters
        allowed_kwargs = {
            "debug_mode",
            "monitoring",
        }
        
        # Check for unallowed parameters
        unallowed_params = set(kwargs.keys()) - allowed_kwargs
        if unallowed_params:
            raise ValueError(
                f"WorkflowAgent does not support the following parameters: {', '.join(sorted(unallowed_params))}.\n"
                f"Allowed parameters are:\n"
                f"  - Core: model (required), name, description, instructions\n"
                f"  - Additional: {', '.join(sorted(allowed_kwargs))}\n"
                f"Not allowed: tools, knowledge, db, reasoning, and other Agent-specific parameters"
            )
        
        # Filter kwargs to only allow specific parameters
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_kwargs}
        
        super().__init__(
            model=model,
            name=name,
            description=description or "Workflow orchestration agent that decides when to run workflows",
            instructions=instructions,
            tools=None,  # Tools will be set by workflow
            knowledge=None,
            db=None,  # No separate DB for workflow agent
            **filtered_kwargs,
        )
        
        # Store reference to workflow for tool creation
        self._workflow = None
        self._workflow_session = None
        self._workflow_session_state = None
        self._workflow_execution_input = None
    
    def create_workflow_tool(
        self,
        workflow: "Any",  # Workflow type
        session: "WorkflowSession",
        execution_input: "WorkflowExecutionInput",
        session_state: Optional[Dict[str, Any]],
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
        from agno.utils.log import log_debug
        from pydantic import BaseModel
        from datetime import datetime
        from uuid import uuid4
        from agno.run.workflow import WorkflowRunOutput
        from agno.workflow.types import WorkflowExecutionInput
        
        # Store references for the tool
        self._workflow = workflow
        self._workflow_session = session
        self._workflow_session_state = session_state
        self._workflow_execution_input = execution_input
        
        def run_workflow(query: str) -> str:
            """
            Execute the complete workflow with the given query.
            Use this tool when you need to run the workflow to answer the user's question.
            
            Args:
                query: The input query/question to process through the workflow
            
            Returns:
                The workflow execution result
            """
            logger.info("=" * 80)
            logger.info(" TOOL EXECUTION: run_workflow")
            logger.info(f"    ➜ Query: {query[:100]}{'...' if len(query) > 100 else ''}")
            logger.info("=" * 80)
            
            # Create a new run ID for this execution
            run_id = str(uuid4())
            log_debug(f" Created new run ID: {run_id}")
            
            # Create workflow run response
            workflow_run_response = WorkflowRunOutput(
                run_id=run_id,
                input=query,
                session_id=session.session_id,
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
            
            # Execute the workflow (non-streaming)
            log_debug(" Executing workflow steps...")
            result = workflow._execute(
                session=session,
                execution_input=workflow_execution_input,
                workflow_run_response=workflow_run_response,
                session_state=session_state,
            )
            
            logger.info("=" * 80)
            logger.info(f" TOOL EXECUTION COMPLETE: run_workflow")
            logger.info(f"    ➜ Run ID: {result.run_id}")
            logger.info(f"    ➜ Result length: {len(str(result.content)) if result.content else 0} chars")
            logger.info("=" * 80)
            
            # Return the content as string
            if isinstance(result.content, str):
                return result.content
            elif isinstance(result.content, BaseModel):
                return result.content.model_dump_json(exclude_none=True)
            else:
                return str(result.content)
        
        return run_workflow
    
    def validate_for_workflow(self) -> None:
        """Validate that the agent is properly configured for workflow use"""
        if not self.model:
            raise ValueError("WorkflowAgent requires a model to be specified")
        
        if self.knowledge:
            raise ValueError("WorkflowAgent does not support knowledge bases")
        
        if self.db:
            raise ValueError("WorkflowAgent does not support separate database, it automatically uses the workflow's database")
