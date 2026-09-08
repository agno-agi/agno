import json
import re
from textwrap import dedent
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error
from agno.workflow.workflow import Workflow, WorkflowRunOutput


class RunWorkflowInput(BaseModel):
    input_data: str = Field(..., description="The input data for the workflow.")
    additional_data: Optional[Dict[str, Any]] = Field(default=None, description="The additional data for the workflow.")


def _sanitize_tool_name_component(value: str) -> str:
    """Turn a workflow id/name into a tool-name-safe component."""
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    if cleaned and cleaned[0].isdigit():
        cleaned = f"wf_{cleaned}"
    return cleaned or "workflow"


class WorkflowTools(Toolkit):
    """Toolkit that exposes a Workflow as agent tools.

    By default tool names stay ``run_workflow`` / ``think`` / ``analyze`` for
    backward compatibility. To attach multiple ``WorkflowTools`` to one Agent or
    Team without collisions, use one of:

    - ``unique=True`` — auto-suffix from ``workflow.id`` or ``workflow.name``
    - ``name_prefix="blog"`` — ``run_workflow_blog``, ``think_blog``, ...
    - ``tool_name="run_blog_workflow"`` — explicit run-tool override
    """

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
        tool_name: Optional[str] = None,
        name_prefix: Optional[str] = None,
        unique: bool = False,
        **kwargs,
    ):
        """Initialize WorkflowTools.

        Args:
            workflow: The workflow to expose as tools.
            enable_run_workflow: Register the run tool.
            enable_think: Register the think scratchpad tool.
            enable_analyze: Register the analyze tool.
            all: Enable run, think, and analyze.
            instructions: Optional custom toolkit instructions.
            add_instructions: Whether to add toolkit instructions to the agent.
            add_few_shot: Append few-shot examples to default instructions.
            few_shot_examples: Few-shot examples to append when ``add_few_shot`` is True.
            async_mode: Register async entrypoints.
            tool_name: Explicit name for the run tool (overrides the default / prefixed name).
            name_prefix: Prefix/suffix component for run/think/analyze tool names.
            unique: When True (and ``name_prefix`` is omitted), derive a name prefix from
                ``workflow.id`` or ``workflow.name`` so multiple toolkits do not collide.
            **kwargs: Forwarded to ``Toolkit``.
        """
        # The workflow to execute
        self.workflow: Workflow = workflow

        # Resolve tool names. Defaults stay `run_workflow` / `think` / `analyze` for
        # backward compatibility. Use `tool_name`, `name_prefix`, or `unique=True`
        # so multiple WorkflowTools can coexist on one Agent/Team.
        prefix = name_prefix
        if unique and not prefix:
            prefix = workflow.id or workflow.name or "workflow"
        if prefix:
            prefix = _sanitize_tool_name_component(prefix)

        self.name_prefix: Optional[str] = prefix
        self.run_tool_name: str = tool_name or (f"run_workflow_{prefix}" if prefix else "run_workflow")
        self.think_tool_name: str = f"think_{prefix}" if prefix else "think"
        self.analyze_tool_name: str = f"analyze_{prefix}" if prefix else "analyze"

        if instructions is None:
            self.instructions = self._default_instructions(
                run_name=self.run_tool_name,
                think_name=self.think_tool_name,
                analyze_name=self.analyze_tool_name,
                workflow=workflow,
            )
            if add_few_shot and few_shot_examples is not None:
                self.instructions += "\n" + few_shot_examples
        else:
            self.instructions = instructions

        toolkit_name = f"workflow_tools_{prefix}" if prefix else kwargs.pop("name", "workflow_tools")
        if prefix:
            kwargs.pop("name", None)

        super().__init__(
            name=toolkit_name,
            instructions=self.instructions,
            add_instructions=add_instructions,
            auto_register=False,
            **kwargs,
        )

        if enable_think or all:
            if async_mode:
                self.register(self.async_think, name=self.think_tool_name)
            else:
                self.register(self.think, name=self.think_tool_name)
            self._set_tool_description(
                self.think_tool_name,
                self._think_description(workflow=workflow, tool_name=self.think_tool_name),
            )
        if enable_run_workflow or all:
            if async_mode:
                self.register(self.async_run_workflow, name=self.run_tool_name)
            else:
                self.register(self.run_workflow, name=self.run_tool_name)
            self._set_tool_description(
                self.run_tool_name,
                self._run_description(workflow=workflow, tool_name=self.run_tool_name),
            )
        if enable_analyze or all:
            if async_mode:
                self.register(self.async_analyze, name=self.analyze_tool_name)
            else:
                self.register(self.analyze, name=self.analyze_tool_name)
            self._set_tool_description(
                self.analyze_tool_name,
                self._analyze_description(workflow=workflow, tool_name=self.analyze_tool_name),
            )

    def _set_tool_description(self, name: str, description: str) -> None:
        fn = self.functions.get(name) or self.async_functions.get(name)
        if fn is not None:
            fn.description = description

    @staticmethod
    def _workflow_label(workflow: Workflow) -> str:
        return workflow.name or workflow.id or "workflow"

    @classmethod
    def _run_description(cls, workflow: Workflow, tool_name: str) -> str:
        label = cls._workflow_label(workflow)
        parts = [
            f"Execute the '{label}' workflow via `{tool_name}`.",
        ]
        if workflow.id:
            parts.append(f"Workflow id: {workflow.id}.")
        if workflow.description:
            desc = workflow.description.strip()
            if not desc.endswith("."):
                desc += "."
            parts.append(desc)
        parts.append("Pass input_data and optional additional_data.")
        return " ".join(parts)

    @classmethod
    def _think_description(cls, workflow: Workflow, tool_name: str) -> str:
        label = cls._workflow_label(workflow)
        return (
            f"Scratchpad (`{tool_name}`) for planning execution of the '{label}' workflow: "
            "brainstorm inputs, refine approach, or decide strategy. Notes are not shown to the user."
        )

    @classmethod
    def _analyze_description(cls, workflow: Workflow, tool_name: str) -> str:
        label = cls._workflow_label(workflow)
        return (
            f"Evaluate (`{tool_name}`) whether results from the '{label}' workflow are correct and sufficient. "
            "If not, go back to think or run with refined inputs."
        )

    @classmethod
    def _default_instructions(
        cls,
        run_name: str,
        think_name: str,
        analyze_name: str,
        workflow: Workflow,
    ) -> str:
        label = cls._workflow_label(workflow)
        identity = f"'{label}'"
        if workflow.id and workflow.name and workflow.id != workflow.name:
            identity = f"'{workflow.name}' (id={workflow.id})"
        elif workflow.id and not workflow.name:
            identity = f"id={workflow.id}"

        return dedent(f"""\
            You have access to tools for the {identity} workflow. Use these tools as frequently as needed to complete workflow-based tasks.
            ## How to use the Think, Run Workflow, and Analyze tools:

            1. **Think** (`{think_name}`)
            - Purpose: A scratchpad for planning workflow execution, brainstorming inputs, and refining your approach. You never reveal your "Think" content to the user.
            - Usage: Call `{think_name}` whenever you need to figure out what workflow inputs to use, analyze requirements, or decide on execution strategy before (or after) you run the workflow.
            2. **Run Workflow** (`{run_name}`)
            - Purpose: Executes the {identity} workflow with specified inputs and parameters.
            - Usage: Call `{run_name}` with appropriate input data whenever you want to execute this workflow.
                - For all workflows, start with simple inputs and gradually increase complexity
            3. **Analyze** (`{analyze_name}`)
            - Purpose: Evaluate whether the workflow execution results are correct and sufficient. If not, go back to "Think" or "Run Workflow" with refined inputs.
            - Usage: Call `{analyze_name}` after getting workflow results to verify the quality and correctness of the execution. Consider:
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

    def think(self, run_context: RunContext, thought: str) -> str:
        """Use this tool as a scratchpad to reason about the workflow execution, refine your approach, brainstorm workflow inputs, or revise your plan.
        Call `Think` whenever you need to figure out what to do next, analyze the user's requirements, plan workflow inputs, or decide on execution strategy.
        You should use this tool as frequently as needed.
        Args:
            thought: Your thought process and reasoning about workflow execution.
        """
        try:
            log_debug(f"Workflow Thought: {thought}")

            # Add the thought to the session state
            if run_context.session_state is None:
                run_context.session_state = {}
            if "workflow_thoughts" not in run_context.session_state:
                run_context.session_state["workflow_thoughts"] = []
            run_context.session_state["workflow_thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in run_context.session_state["workflow_thoughts"]])
            formatted_thoughts = dedent(
                f"""Workflow Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            log_error(f"Error recording workflow thought: {str(e)}")
            return f"Error recording workflow thought: {e}"

    async def async_think(self, run_context: RunContext, thought: str) -> str:
        """Use this tool as a scratchpad to reason about the workflow execution, refine your approach, brainstorm workflow inputs, or revise your plan.
        Call `Think` whenever you need to figure out what to do next, analyze the user's requirements, plan workflow inputs, or decide on execution strategy.
        You should use this tool as frequently as needed.
        Args:
            thought: Your thought process and reasoning about workflow execution.
        """
        try:
            log_debug(f"Workflow Thought: {thought}")

            # Add the thought to the session state
            if run_context.session_state is None:
                run_context.session_state = {}
            if "workflow_thoughts" not in run_context.session_state:
                run_context.session_state["workflow_thoughts"] = []
            run_context.session_state["workflow_thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in run_context.session_state["workflow_thoughts"]])
            formatted_thoughts = dedent(
                f"""Workflow Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            log_error(f"Error recording workflow thought: {str(e)}")
            return f"Error recording workflow thought: {e}"

    def run_workflow(
        self,
        run_context: RunContext,
        input: RunWorkflowInput,
    ) -> str:
        """Use this tool to execute the workflow with the specified inputs and parameters.
        After thinking through the requirements, use this tool to run the workflow with appropriate inputs.

        Args:
            input: The input data for the workflow.
        """
        if isinstance(input, dict):
            input = RunWorkflowInput.model_validate(input)

        try:
            log_debug(f"Running workflow with input: {input.input_data}")

            if run_context.session_state is None:
                run_context.session_state = {}

            # Execute the workflow
            result: WorkflowRunOutput = self.workflow.run(
                input=input.input_data,
                user_id=run_context.user_id,
                session_id=run_context.session_id,
                session_state=run_context.session_state,
                additional_data=input.additional_data,
            )

            if "workflow_results" not in run_context.session_state:
                run_context.session_state["workflow_results"] = []

            run_context.session_state["workflow_results"].append(result.to_dict())

            return json.dumps(result.to_dict(), indent=2)

        except Exception as e:
            log_error(f"Error running workflow: {str(e)}")
            return f"Error running workflow: {e}"

    async def async_run_workflow(
        self,
        run_context: RunContext,
        input: RunWorkflowInput,
    ) -> str:
        """Use this tool to execute the workflow with the specified inputs and parameters.
        After thinking through the requirements, use this tool to run the workflow with appropriate inputs.
        Args:
            input_data: The input data for the workflow (use a `str` for a simple input)
            additional_data: The additional data for the workflow. This is a dictionary of key-value pairs that will be passed to the workflow. E.g. {"topic": "food", "style": "Humour"}
        """
        if isinstance(input, dict):
            input = RunWorkflowInput.model_validate(input)

        try:
            log_debug(f"Running workflow with input: {input.input_data}")

            if run_context.session_state is None:
                run_context.session_state = {}

            # Execute the workflow
            result: WorkflowRunOutput = await self.workflow.arun(
                input=input.input_data,
                user_id=run_context.user_id,
                session_id=run_context.session_id,
                session_state=run_context.session_state,
                additional_data=input.additional_data,
            )

            if "workflow_results" not in run_context.session_state:
                run_context.session_state["workflow_results"] = []

            run_context.session_state["workflow_results"].append(result.to_dict())

            return json.dumps(result.to_dict(), indent=2)

        except Exception as e:
            log_error(f"Error running workflow: {str(e)}")
            return f"Error running workflow: {e}"

    def analyze(self, run_context: RunContext, analysis: str) -> str:
        """Use this tool to evaluate whether the workflow execution results are correct and sufficient.
        If not, go back to "Think" or "Run" with refined inputs or parameters.
        Args:
            analysis: Your analysis of the workflow execution results.
        """
        try:
            log_debug(f"Workflow Analysis: {analysis}")

            # Add the analysis to the session state
            if run_context.session_state is None:
                run_context.session_state = {}
            if "workflow_analysis" not in run_context.session_state:
                run_context.session_state["workflow_analysis"] = []
            run_context.session_state["workflow_analysis"].append(analysis)

            # Return the full log of analysis and the new analysis
            analysis_log = "\n".join([f"- {a}" for a in run_context.session_state["workflow_analysis"]])
            formatted_analysis = dedent(
                f"""Workflow Analysis:
                {analysis_log}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            log_error(f"Error recording workflow analysis: {str(e)}")
            return f"Error recording workflow analysis: {e}"

    async def async_analyze(self, run_context: RunContext, analysis: str) -> str:
        """Use this tool to evaluate whether the workflow execution results are correct and sufficient.
        If not, go back to "Think" or "Run" with refined inputs or parameters.
        Args:
            analysis: Your analysis of the workflow execution results.
        """
        try:
            log_debug(f"Workflow Analysis: {analysis}")

            # Add the analysis to the session state
            if run_context.session_state is None:
                run_context.session_state = {}
            if "workflow_analysis" not in run_context.session_state:
                run_context.session_state["workflow_analysis"] = []
            run_context.session_state["workflow_analysis"].append(analysis)

            # Return the full log of analysis and the new analysis
            analysis_log = "\n".join([f"- {a}" for a in run_context.session_state["workflow_analysis"]])
            formatted_analysis = dedent(
                f"""Workflow Analysis:
                {analysis_log}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            log_error(f"Error recording workflow analysis: {str(e)}")
            return f"Error recording workflow analysis: {e}"
