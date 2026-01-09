import json
import warnings
from textwrap import dedent
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from pydantic import BaseModel, Field, ValidationError

from agno.run.base import RunContext
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutputEvent
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error
from agno.workflow.workflow import Workflow, WorkflowRunOutput


class RunWorkflowInput(BaseModel):
    input_data: str = Field(..., description="The input data for the workflow.")
    additional_data: Optional[Dict[str, Any]] = Field(default=None, description="The additional data for the workflow.")


class WorkflowTools(Toolkit):
    def __init__(
        self,
        workflow: Workflow,
        enable_run_workflow: bool = True,
        enable_think: bool = False,
        enable_analyze: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        add_few_shot: bool = False,
        few_shot_examples: Optional[str] = None,
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        # Deprecated parameter
        async_mode: Optional[bool] = None,
        **kwargs,
    ):
        """Initialize WorkflowTools.

        Args:
            workflow: The workflow to execute.
            enable_run_workflow: Enable the run_workflow tool.
            enable_think: Enable the think tool.
            enable_analyze: Enable the analyze tool.
            all: Enable all tools.
            instructions: Custom instructions for the toolkit.
            add_instructions: Whether to add instructions to the system message.
            add_few_shot: Whether to add few-shot examples.
            few_shot_examples: Custom few-shot examples.
            stream: Whether to stream workflow output. If None, inherits from run_context at runtime.
            stream_events: Whether to stream workflow events. If None, inherits from run_context at runtime.
            async_mode: Deprecated. Async tools are now automatically registered.
        """
        # Handle deprecated async_mode parameter
        if async_mode is not None:
            warnings.warn(
                "The 'async_mode' parameter is deprecated and will be removed in future versions. "
                "Async tools are now automatically registered alongside sync tools.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Add instructions for using this toolkit
        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
            if add_few_shot:
                if few_shot_examples is not None:
                    self.instructions += "\n" + few_shot_examples
        else:
            self.instructions = instructions

        # The workflow to execute
        self.workflow: Workflow = workflow

        # Streaming settings - None means inherit from run_context at runtime
        self._stream: Optional[bool] = stream
        self._stream_events: Optional[bool] = stream_events

        # Build tools lists
        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[tuple] = []

        if enable_think or all:
            tools.append(self.think)
            async_tools.append((self.async_think, "think"))
        if enable_run_workflow or all:
            tools.append(self.run_workflow)
            async_tools.append((self.async_run_workflow, "run_workflow"))
        if enable_analyze or all:
            tools.append(self.analyze)
            async_tools.append((self.async_analyze, "analyze"))

        super().__init__(
            name="workflow_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _should_stream(self, run_context: Optional[RunContext] = None) -> bool:
        """Determine if workflow should stream based on settings and run_context.

        Args:
            run_context: The run context (injected at runtime).

        Returns:
            True if streaming should be enabled.
        """
        # If explicitly set on WorkflowTools, use that
        if self._stream is not None:
            return self._stream
        # Otherwise inherit from run_context if available
        if run_context is not None:
            return run_context.stream
        # Default to True
        return True

    def _should_stream_events(self, run_context: Optional[RunContext] = None) -> bool:
        """Determine if workflow events should be streamed based on settings and run_context.

        Args:
            run_context: The run context (injected at runtime).

        Returns:
            True if event streaming should be enabled.
        """
        # If explicitly set on WorkflowTools, use that
        if self._stream_events is not None:
            return self._stream_events
        # Otherwise inherit from run_context if available
        if run_context is not None:
            return run_context.stream_events
        # Default to True when streaming
        return True

    def think(self, session_state: Dict[str, Any], thought: str) -> str:
        """Use this tool as a scratchpad to reason about the workflow execution, refine your approach, brainstorm workflow inputs, or revise your plan.
        Call `Think` whenever you need to figure out what to do next, analyze the user's requirements, plan workflow inputs, or decide on execution strategy.
        You should use this tool as frequently as needed.
        Args:
            thought: Your thought process and reasoning about workflow execution.
        """
        try:
            log_debug(f"Workflow Thought: {thought}")

            # Add the thought to the session state
            if session_state is None:
                session_state = {}
            if "workflow_thoughts" not in session_state:
                session_state["workflow_thoughts"] = []
            session_state["workflow_thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in session_state["workflow_thoughts"]])
            formatted_thoughts = dedent(
                f"""Workflow Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            log_error(f"Error recording workflow thought: {e}")
            return f"Error recording workflow thought: {e}"

    async def async_think(self, session_state: Dict[str, Any], thought: str) -> str:
        """Use this tool as a scratchpad to reason about the workflow execution, refine your approach, brainstorm workflow inputs, or revise your plan.
        Call `Think` whenever you need to figure out what to do next, analyze the user's requirements, plan workflow inputs, or decide on execution strategy.
        You should use this tool as frequently as needed.
        Args:
            thought: Your thought process and reasoning about workflow execution.
        """
        try:
            log_debug(f"Workflow Thought: {thought}")

            # Add the thought to the session state
            if session_state is None:
                session_state = {}
            if "workflow_thoughts" not in session_state:
                session_state["workflow_thoughts"] = []
            session_state["workflow_thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in session_state["workflow_thoughts"]])
            formatted_thoughts = dedent(
                f"""Workflow Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            log_error(f"Error recording workflow thought: {e}")
            return f"Error recording workflow thought: {e}"

    def run_workflow(
        self,
        run_context: RunContext,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
    ) -> Union[str, Iterator[Union[WorkflowRunOutputEvent, str]]]:
        """Use this tool to execute the workflow with the specified inputs and parameters.
        After thinking through the requirements, use this tool to run the workflow with appropriate inputs.

        Args:
            input: The input data for the workflow.
        """
        try:
            if isinstance(input, dict):
                input = RunWorkflowInput.model_validate(input)
        except ValidationError as e:
            log_error(f"Invalid workflow input: {e}")
            return f"Invalid workflow input: {e}"

        # Check if we should stream based on run_context settings
        should_stream = self._should_stream(run_context)
        should_stream_events = self._should_stream_events(run_context)

        if should_stream:
            return self._run_workflow_stream(session_state, input, stream_events=should_stream_events)
        else:
            return self._run_workflow(session_state, input)

    def _run_workflow(
        self,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
    ) -> str:
        """Execute workflow synchronously without streaming events."""
        try:
            log_debug(f"Running workflow with input: {input.input_data}")

            user_id = session_state.get("current_user_id")
            session_id = session_state.get("current_session_id")

            # Execute the workflow
            result: WorkflowRunOutput = self.workflow.run(
                input=input.input_data,
                user_id=user_id,
                session_id=session_id,
                session_state=session_state,
                additional_data=input.additional_data,
            )

            if "workflow_results" not in session_state:
                session_state["workflow_results"] = []

            session_state["workflow_results"].append(result.to_dict())

            return json.dumps(result.to_dict(), indent=2)

        except Exception as e:
            log_error(f"Error running workflow: {e}")
            return f"Error running workflow: {e}"

    def _run_workflow_stream(
        self,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
        stream_events: bool = True,
    ) -> Iterator[Union[WorkflowRunOutputEvent, str]]:
        """Execute workflow with streaming events."""
        try:
            log_debug(f"Running workflow (streaming) with input: {input.input_data}")

            user_id = session_state.get("current_user_id")
            session_id = session_state.get("current_session_id")

            # Execute the workflow with streaming
            final_content = ""

            for event in self.workflow.run(
                input=input.input_data,
                user_id=user_id,
                session_id=session_id,
                session_state=session_state,
                additional_data=input.additional_data,
                stream=True,
                stream_events=stream_events,
            ):
                # Yield workflow events for display
                yield event

                # Capture the final content from WorkflowCompletedEvent
                if isinstance(event, WorkflowCompletedEvent):
                    if event.content is not None:
                        if isinstance(event.content, BaseModel):
                            final_content = event.content.model_dump_json()
                        else:
                            final_content = str(event.content)

            if "workflow_results" not in session_state:
                session_state["workflow_results"] = []

            if final_content:
                session_state["workflow_results"].append({"content": final_content})

            # Yield final content as the tool result
            yield final_content

        except Exception as e:
            log_error(f"Error running workflow: {e}")
            yield f"Error running workflow: {e}"

    async def async_run_workflow(
        self,
        run_context: RunContext,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
    ) -> Union[str, AsyncIterator[Union[WorkflowRunOutputEvent, str]]]:
        """Use this tool to execute the workflow with the specified inputs and parameters.
        After thinking through the requirements, use this tool to run the workflow with appropriate inputs.

        Args:
            input: The input data for the workflow.
        """
        try:
            if isinstance(input, dict):
                input = RunWorkflowInput.model_validate(input)
        except ValidationError as e:
            log_error(f"Invalid workflow input: {e}")
            return f"Invalid workflow input: {e}"

        # Check if we should stream based on run_context settings
        should_stream = self._should_stream(run_context)
        should_stream_events = self._should_stream_events(run_context)

        if should_stream and should_stream_events:
            return self._async_run_workflow_stream(session_state, input, stream_events=should_stream_events)
        else:
            return await self._async_run_workflow(session_state, input)

    async def _async_run_workflow(
        self,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
    ) -> str:
        """Execute workflow asynchronously without streaming events."""
        try:
            log_debug(f"Running workflow with input: {input.input_data}")

            user_id = session_state.get("current_user_id")
            session_id = session_state.get("current_session_id")

            # Execute the workflow
            result: WorkflowRunOutput = await self.workflow.arun(
                input=input.input_data,
                user_id=user_id,
                session_id=session_id,
                session_state=session_state,
                additional_data=input.additional_data,
            )

            if "workflow_results" not in session_state:
                session_state["workflow_results"] = []

            session_state["workflow_results"].append(result.to_dict())

            return json.dumps(result.to_dict(), indent=2)

        except Exception as e:
            log_error(f"Error running workflow: {e}")
            return f"Error running workflow: {e}"

    async def _async_run_workflow_stream(
        self,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
        stream_events: bool = True,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, str]]:
        """Execute workflow asynchronously with streaming events."""
        try:
            log_debug(f"Running workflow (streaming) with input: {input.input_data}")

            user_id = session_state.get("current_user_id")
            session_id = session_state.get("current_session_id")

            # Execute the workflow with streaming
            final_content = ""

            async for event in self.workflow.arun(
                input=input.input_data,
                user_id=user_id,
                session_id=session_id,
                session_state=session_state,
                additional_data=input.additional_data,
                stream=True,
                stream_events=stream_events,
            ):
                # Yield workflow events for display
                yield event

                # Capture the final content from WorkflowCompletedEvent
                if isinstance(event, WorkflowCompletedEvent):
                    if event.content is not None:
                        if isinstance(event.content, BaseModel):
                            final_content = event.content.model_dump_json()
                        else:
                            final_content = str(event.content)

            if "workflow_results" not in session_state:
                session_state["workflow_results"] = []

            if final_content:
                session_state["workflow_results"].append({"content": final_content})

            # Yield final content as the tool result
            yield final_content

        except Exception as e:
            log_error(f"Error running workflow: {e}")
            yield f"Error running workflow: {e}"

    def analyze(self, session_state: Dict[str, Any], analysis: str) -> str:
        """Use this tool to evaluate whether the workflow execution results are correct and sufficient.
        If not, go back to "Think" or "Run" with refined inputs or parameters.
        Args:
            analysis: Your analysis of the workflow execution results.
        """
        try:
            log_debug(f"Workflow Analysis: {analysis}")

            # Add the analysis to the session state
            if session_state is None:
                session_state = {}
            if "workflow_analysis" not in session_state:
                session_state["workflow_analysis"] = []
            session_state["workflow_analysis"].append(analysis)

            # Return the full log of analysis and the new analysis
            analysis_log = "\n".join([f"- {a}" for a in session_state["workflow_analysis"]])
            formatted_analysis = dedent(
                f"""Workflow Analysis:
                {analysis_log}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            log_error(f"Error recording workflow analysis: {e}")
            return f"Error recording workflow analysis: {e}"

    async def async_analyze(self, session_state: Dict[str, Any], analysis: str) -> str:
        """Use this tool to evaluate whether the workflow execution results are correct and sufficient.
        If not, go back to "Think" or "Run" with refined inputs or parameters.
        Args:
            analysis: Your analysis of the workflow execution results.
        """
        try:
            log_debug(f"Workflow Analysis: {analysis}")

            # Add the analysis to the session state
            if session_state is None:
                session_state = {}
            if "workflow_analysis" not in session_state:
                session_state["workflow_analysis"] = []
            session_state["workflow_analysis"].append(analysis)

            # Return the full log of analysis and the new analysis
            analysis_log = "\n".join([f"- {a}" for a in session_state["workflow_analysis"]])
            formatted_analysis = dedent(
                f"""Workflow Analysis:
                {analysis_log}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            log_error(f"Error recording workflow analysis: {e}")
            return f"Error recording workflow analysis: {e}"

    DEFAULT_INSTRUCTIONS = dedent("""\
        You have access to the Think, Run Workflow, and Analyze tools that will help you execute workflows and analyze their results. Use these tools as frequently as needed to successfully complete workflow-based tasks.
        ## How to use the Think, Run Workflow, and Analyze tools:
        
        1. **Think**
        - Purpose: A scratchpad for planning workflow execution, brainstorming inputs, and refining your approach. You never reveal your "Think" content to the user.
        - Usage: Call `think` whenever you need to figure out what workflow inputs to use, analyze requirements, or decide on execution strategy before (or after) you run the workflow.
        2. **Run Workflow**
        - Purpose: Executes the workflow with specified inputs and parameters.
        - Usage: Call `run_workflow` with appropriate input data whenever you want to execute the workflow.
            - For all workflows, start with simple inputs and gradually increase complexity
        3. **Analyze**
        - Purpose: Evaluate whether the workflow execution results are correct and sufficient. If not, go back to "Think" or "Run Workflow" with refined inputs.
        - Usage: Call `analyze` after getting workflow results to verify the quality and correctness of the execution. Consider:
            - Completeness: Did the workflow complete all expected steps?
            - Quality: Are the results accurate and meet the requirements?
            - Errors: Were there any failures or unexpected behaviors?
        **Important Guidelines**:
        - Do not include your internal chain-of-thought in direct user responses.
        - Use "Think" to reason internally. These notes are never exposed to the user.
        - When you provide a final answer to the user, be clear, concise, and based on the workflow results.
        - If workflow execution fails or produces unexpected results, acknowledge limitations and explain what went wrong.
        - Synthesize information from multiple workflow runs if you execute the workflow several times with different inputs.\
    """)
