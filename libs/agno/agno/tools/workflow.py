import json
from textwrap import dedent
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

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
        async_mode: bool = False,
        **kwargs,
    ):
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

        super().__init__(
            name="workflow_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            auto_register=False,
            **kwargs,
        )

        if enable_think or all:
            if async_mode:
                self.register(self.async_think, name="think")
            else:
                self.register(self.think, name="think")
        if enable_run_workflow or all:
            if async_mode:
                self.register(self.async_run_workflow, name="run_workflow")
            else:
                self.register(self.run_workflow, name="run_workflow")
        if enable_analyze or all:
            if async_mode:
                self.register(self.async_analyze, name="analyze")
            else:
                self.register(self.analyze, name="analyze")

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
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
    ) -> str:
        """Use this tool to execute the workflow with the specified inputs and parameters.
        After thinking through the requirements, use this tool to run the workflow with appropriate inputs.
        Args:
            input_data: The input data for the workflow.
        """
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

    async def async_run_workflow(
        self,
        session_state: Dict[str, Any],
        input: RunWorkflowInput,
    ) -> str:
        """Use this tool to execute the workflow with the specified inputs and parameters.
        After thinking through the requirements, use this tool to run the workflow with appropriate inputs.
        Args:
            input_data: The input data for the workflow (use a `str` for a simple input)
            additional_data: The additional data for the workflow. This is a dictionary of key-value pairs that will be passed to the workflow. E.g. {"topic": "food", "style": "Humour"}
        """
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
