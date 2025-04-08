from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.reasoning.step import NextAction, ReasoningStep
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class ReasoningTools(Toolkit):
    def __init__(
        self,
        think: bool = True,
        analyze: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        add_few_shot: bool = False,
        few_shot_examples: Optional[str] = None,
        **kwargs,
    ):
        """A toolkit that provides step-by-step reasoning tools: Think and Analyze."""
        super().__init__(
            name="reasoning_tools",
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        # Add instructions for using this toolkit
        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
            if add_few_shot:
                if few_shot_examples is not None:
                    self.instructions += "\n" + few_shot_examples
                else:
                    self.instructions += "\n" + self.FEW_SHOT_EXAMPLES

        # Register each tool based on the init flags
        if think:
            self.register(self.think)
        if analyze:
            self.register(self.analyze)

    def think(
        self, agent: Agent, title: str, thought: str, action: Optional[str] = None, confidence: float = 0.8
    ) -> str:
        """Use this tool as a scratchpad to reason about the question and work through it step-by-step.
        This tool will help you break down complex problems into logical steps and track the reasoning process.
        You can call it as many times as needed. These internal thoughts are never revealed to the user.

        Args:
            title: A concise title for this step
            thought: Your detailed thought for this step
            action: What you'll do based on this thought
            confidence: How confident you are about this thought (0.0 to 1.0)

        Returns:
            A summary of the reasoning step
        """
        try:
            log_debug(f"Thought: {title}")

            # Create a reasoning step
            reasoning_step = ReasoningStep(
                title=title,
                reasoning=thought,
                action=action,
                next_action=NextAction.CONTINUE,
                confidence=confidence,
            )

            # Add this step to the Agent's session state
            if agent.session_state is None:
                agent.session_state = {}

            if "reasoning_steps" not in agent.session_state:
                agent.session_state["reasoning_steps"] = []

            agent.session_state["reasoning_steps"].append(reasoning_step)

            # Add the step to the run response
            if hasattr(agent, "run_response") and agent.run_response is not None:
                if agent.run_response.extra_data is None:
                    from agno.run.response import RunResponseExtraData

                    agent.run_response.extra_data = RunResponseExtraData()

                if agent.run_response.extra_data.reasoning_steps is None:
                    agent.run_response.extra_data.reasoning_steps = []

                agent.run_response.extra_data.reasoning_steps.append(reasoning_step)

            # Return all previous reasoning_steps and the new reasoning_step
            if "reasoning_steps" in agent.session_state:
                formatted_reasoning_steps = ""
                for i, step in enumerate(agent.session_state["reasoning_steps"], 1):
                    formatted_reasoning_steps += f"""
                    Step {i}:
                    Title: {step.title}
                    Reasoning: {step.reasoning}
                    Action: {step.action}
                    Confidence: {step.confidence}
                    """
                return formatted_reasoning_steps
            return reasoning_step.model_dump_json()
        except Exception as e:
            log_error(f"Error recording thought: {e}")
            return f"Error recording thought: {e}"

    def analyze(
        self,
        agent: Agent,
        title: str,
        result: str,
        analysis: str,
        next_action: str = "continue",
        confidence: float = 0.8,
    ) -> str:
        """Use this tool to analyze results from a reasoning step and determine next actions.

        Args:
            title: A concise title for this analysis step
            result: The outcome of the previous action
            analysis: Your analysis of the results
            next_action: What to do next ("continue", "validate", or "final_answer")
            confidence: How confident you are in this analysis (0.0 to 1.0)

        Returns:
            A summary of the analysis
        """
        try:
            log_debug(f"Analysis step: {title}")

            # Map string next_action to enum
            next_action_enum = NextAction.CONTINUE
            if next_action.lower() == "validate":
                next_action_enum = NextAction.VALIDATE
            elif next_action.lower() in ["final", "final_answer", "finalize"]:
                next_action_enum = NextAction.FINAL_ANSWER

            # Create a reasoning step for the analysis
            reasoning_step = ReasoningStep(
                title=title,
                result=result,
                reasoning=analysis,
                next_action=next_action_enum,
                confidence=confidence,
            )

            # Add this step to the Agent's session state
            if agent.session_state is None:
                agent.session_state = {}

            if "reasoning_steps" not in agent.session_state:
                agent.session_state["reasoning_steps"] = []

            agent.session_state["reasoning_steps"].append(reasoning_step)

            # Add the step to the run response if we can
            if hasattr(agent, "run_response") and agent.run_response is not None:
                if agent.run_response.extra_data is None:
                    from agno.run.response import RunResponseExtraData

                    agent.run_response.extra_data = RunResponseExtraData()

                if agent.run_response.extra_data.reasoning_steps is None:
                    agent.run_response.extra_data.reasoning_steps = []

                agent.run_response.extra_data.reasoning_steps.append(reasoning_step)

            # Return all previous reasoning_steps and the new reasoning_step
            if "reasoning_steps" in agent.session_state:
                formatted_reasoning_steps = ""
                for i, step in enumerate(agent.session_state["reasoning_steps"], 1):
                    formatted_reasoning_steps += f"""
                    Step {i}:
                    Title: {step.title}
                    Reasoning: {step.reasoning}
                    Action: {step.action}
                    Confidence: {step.confidence}
                    """
                return formatted_reasoning_steps
            return reasoning_step.model_dump_json()
        except Exception as e:
            log_error(f"Error recording analysis: {e}")
            return f"Error recording analysis: {e}"

    # --------------------------------------------------------------------------------
    # Default instructions and few-shot examples
    # --------------------------------------------------------------------------------

    DEFAULT_INSTRUCTIONS = dedent(
        """\
        You have access to the Think and Analyze tools that will help you work through problems step-by-step and structure your thinking process. You must always `think` before making a tool call or generating an answer.

        1. **Think** (scratchpad):
            - Purpose: Use the `think` tool as a scratchpad to break down complex problems, outline steps, and decide on immediate actions within your reasoning flow. Use this to structure your internal monologue.
            - Usage: Call `think` multiple times to build a chain of thought. Detail your reasoning for each step and specify the intended action (e.g., "make a tool call", "perform calculation", "ask clarifying question").
                You must always `think` before making a tool call or generating an answer.

        2. **Analyze** (evaluation):
            - Purpose: Evaluate the result of a think step or tool call. Assess if the result is expected, sufficient, or requires further investigation.
            - Usage: Call `analyze` after a `think` step or a tool call. Determine the `next_action` based on your analysis: `continue` (more reasoning needed), `validate` (seek external confirmation/validation if possible), or `final_answer` (ready to conclude).
                Also note your reasoning about whether it's correct/sufficient.

        **IMPORTANT:**
        - You must complete atleast 1 `think` -> `analyze` cycle to reason through the problem.
        - Do not expose your internal chain-of-thought to the user.
        - Use the tools iteratively to build a clear reasoning path: Think -> [Tool Call] -> Analyze -> [Tool Call] -> ... -> Analyze -> Finalize.
        - Iterate through the (Think → Analyze) cycle as many times as needed until you have a satisfactory final answer.
        - If you need more data, refine your approach and call Think/Analyze again.
        - Once you have a satisfactory final answer, provide a concise, clear final answer for the user.
        """
    )

    FEW_SHOT_EXAMPLES = dedent(
        """\
        You can refer to the examples below as guidance for how to use each tool.
        ### Examples

        **Example 1: Basic Step-by-Step**
        User: How many continents are there on Earth?

        Think:
          step_title="Understand the question"
          thought="I need to confirm the standard number of continents."
          action="Recall known information or quickly verify."
          confidence=0.9

        Analyze:
          step_title="Check Basic Fact"
          result="7 continents (commonly accepted: Africa, Antarctica, Asia, Australia, Europe, North America, South America)"
          reasoning="The recalled information confirms the standard count is 7."
          next_action="final_answer"
          confidence=1.0

        Final Answer: There are 7 continents on Earth: Africa, Antarctica, Asia, Australia, Europe, North America, and South America.

        **Example 2: Query Requiring External Information**
        User: What is the capital of France and its current population?

        Think:
          step_title="Plan information retrieval"
          thought="I need two pieces of information: the capital of France and its population. I should use a search tool to find these facts accurately."
          action="Use search tool to find the capital first."
          confidence=0.95

        # Make multiple tool calls to get the information needed
        # [Perform a tool call, e.g., search(query="capital of France")]
        # [Tool Result: "Paris"]
        # [Perform a tool call, e.g., search(query="population of Paris 2024")]
        # [Tool Result: "Approximately 2.1 million (as of early 2024 estimate)"]

        Analyze:
          step_title="Analyze Capital Search Result"
          result="Paris"
          reasoning="The search confirmed Paris is the capital."
          next_action="continue"
          confidence=1.0

        Analyze:
          step_title="Analyze Population Search Result"
          result="Approximately 2.1 million (as of early 2024 estimate)"
          reasoning="The search provided an estimated population figure. I now have both pieces of information requested by the user."
          next_action="final_answer"
          confidence=0.9

        Final Answer: The capital of France is Paris. Its estimated population is approximately 2.1 million as of early 2024.\
        """
    )
