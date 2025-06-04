from textwrap import dedent
from typing import Any, List, Optional, Union

from agno.agent import Agent
from agno.reasoning.step import NextAction, ReasoningStep
from agno.team.team import Team
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

        # Add instructions for using this toolkit
        if instructions is None:
            self.instructions = "<reasoning_instructions>\n" + self.DEFAULT_INSTRUCTIONS
            if add_few_shot:
                if few_shot_examples is not None:
                    self.instructions += "\n" + few_shot_examples
                else:
                    self.instructions += "\n" + self.FEW_SHOT_EXAMPLES
            self.instructions += "\n</reasoning_instructions>\n"
        else:
            self.instructions = instructions

        tools: List[Any] = []
        if think:
            tools.append(self.think)
        if analyze:
            tools.append(self.analyze)

        super().__init__(
            name="reasoning_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    def think(
        self, agent: Union[Agent, Team], title: str, thought: str, action: Optional[str] = None, confidence: float = 0.8
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
            A list of previous thoughts and the new thought
        """
        try:
            log_debug(f"Thought about {title}")

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
                agent.session_state["reasoning_steps"] = {}
            if agent.run_id not in agent.session_state["reasoning_steps"]:
                agent.session_state["reasoning_steps"][agent.run_id] = []
            agent.session_state["reasoning_steps"][agent.run_id].append(reasoning_step.model_dump_json())

            # Return all previous reasoning_steps and the new reasoning_step
            if "reasoning_steps" in agent.session_state and agent.run_id in agent.session_state["reasoning_steps"]:
                formatted_reasoning_steps = ""
                for i, step in enumerate(agent.session_state["reasoning_steps"][agent.run_id], 1):
                    step_parsed = ReasoningStep.model_validate_json(step)
                    step_str = dedent(f"""\
Step {i}:
Title: {step_parsed.title}
Reasoning: {step_parsed.reasoning}
Action: {step_parsed.action}
Confidence: {step_parsed.confidence}
""")
                    formatted_reasoning_steps += step_str + "\n"
                return formatted_reasoning_steps.strip()
            return reasoning_step.model_dump_json()
        except Exception as e:
            log_error(f"Error recording thought: {e}")
            return f"Error recording thought: {e}"

    def analyze(
        self,
        agent: Union[Agent, Team],
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
            A list of previous thoughts and the new analysis
        """
        try:
            log_debug(f"Analyzed {title}")

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
                agent.session_state["reasoning_steps"] = {}
            if agent.run_id not in agent.session_state["reasoning_steps"]:
                agent.session_state["reasoning_steps"][agent.run_id] = []
            agent.session_state["reasoning_steps"][agent.run_id].append(reasoning_step.model_dump_json())

            # Return all previous reasoning_steps and the new reasoning_step
            if "reasoning_steps" in agent.session_state and agent.run_id in agent.session_state["reasoning_steps"]:
                formatted_reasoning_steps = ""
                for i, step in enumerate(agent.session_state["reasoning_steps"][agent.run_id], 1):
                    step_parsed = ReasoningStep.model_validate_json(step)
                    step_str = dedent(f"""\
Step {i}:
Title: {step_parsed.title}
Reasoning: {step_parsed.reasoning}
Action: {step_parsed.action}
Confidence: {step_parsed.confidence}
""")
                    formatted_reasoning_steps += step_str + "\n"
                return formatted_reasoning_steps.strip()
            return reasoning_step.model_dump_json()
        except Exception as e:
            log_error(f"Error recording analysis: {e}")
            return f"Error recording analysis: {e}"

    # --------------------------------------------------------------------------------
    # Default instructions and few-shot examples
    # --------------------------------------------------------------------------------

    DEFAULT_INSTRUCTIONS = dedent(
        """\
        You have access to the `think` and `analyze` tools to work through problems step-by-step and structure your thought process. You must ALWAYS `think` before making tool calls or generating a response.

        1. **Think** (scratchpad):
            - Purpose: Use the `think` tool as a scratchpad to break down complex problems, outline steps, and decide on immediate actions within your reasoning flow. Use this to structure your internal monologue.
            - Usage: Call `think` before making tool calls or generating a response. Explain your reasoning and specify the intended action (e.g., "make a tool call", "perform calculation", "ask clarifying question").

        2. **Analyze** (evaluation):
            - Purpose: Evaluate the result of a think step or a set of tool calls. Assess if the result is expected, sufficient, or requires further investigation.
            - Usage: Call `analyze` after a set of tool calls. Determine the `next_action` based on your analysis: `continue` (more reasoning needed), `validate` (seek external confirmation/validation if possible), or `final_answer` (ready to conclude).
            - Explain your reasoning highlighting whether the result is correct/sufficient.

        ## IMPORTANT GUIDELINES
        - **Always Think First:** You MUST use the `think` tool before making tool calls or generating a response.
        - **Iterate to Solve:** Use the `think` and `analyze` tools iteratively to build a clear reasoning path. The typical flow is `Think` -> [`Tool Calls` if needed] -> [`Analyze` if needed] -> ... -> `final_answer`. Repeat this cycle until you reach a satisfactory conclusion.
        - **Make multiple tool calls in parallel:** After a `think` step, you can make multiple tool calls in parallel.
        - **Keep Thoughts Internal:** The reasoning steps (thoughts and analyses) are for your internal process only. Do not share them directly with the user.
        - **Conclude Clearly:** When your analysis determines the `next_action` is `final_answer`, provide a concise and accurate final answer to the user."""
    )

    FEW_SHOT_EXAMPLES = dedent(
        """
        Below are examples demonstrating how to use the `think` and `analyze` tools.

        ### Examples

        **Example 1: Simple Fact Retrieval**

        *User Request:* How many continents are there on Earth?

        *Agent's Internal Process:*

        ```tool_call
        think(
          title="Understand Request",
          thought="The user wants to know the standard number of continents on Earth. This is a common piece of knowledge.",
          action="Recall or verify the number of continents.",
          confidence=0.95
        )
        ```
        *--(Agent internally recalls the fact)--*
        ```tool_call
        analyze(
          title="Evaluate Fact",
          result="Standard geographical models list 7 continents: Africa, Antarctica, Asia, Australia, Europe, North America, South America.",
          analysis="The recalled information directly answers the user's question accurately.",
          next_action="final_answer",
          confidence=1.0
        )
        ```

        *Agent's Final Answer to User:*
        There are 7 continents on Earth: Africa, Antarctica, Asia, Australia, Europe, North America, and South America.

        **Example 2: Multi-Step Information Gathering**

        *User Request:* What is the capital of France and its current population?

        *Agent's Internal Process:*

        ```tool_call
        think(
          title="Plan Information Retrieval",
          thought="The user needs two pieces of information: the capital of France and its current population. I should use external tools (like search) to find the most up-to-date and accurate information.",
          action="First, search for the capital of France.",
          confidence=0.95
        )
        ```

        *Perform multiple tool calls in parallel*
        *--(Tool call 1: search(query="capital of France"))--*
        *--(Tool call 2: search(query="population of Paris current"))--*
        *--(Tool Result 1: "Paris")--*
        *--(Tool Result 2: "Approximately 2.1 million (city proper, estimate for early 2024)")--*

        ```tool_call
        analyze(
          title="Analyze Capital Search Result",
          result="The search result indicates Paris is the capital of France.",
          analysis="This provides the first piece of requested information. Now I need to find the population of Paris.",
          next_action="continue",
          confidence=1.0
        )
        ```
        ```tool_call
        analyze(
          title="Analyze Population Search Result",
          result="The search provided an estimated population figure for Paris.",
          analysis="I now have both the capital and its estimated population. I can provide the final answer.",
          next_action="final_answer",
          confidence=0.9
        )
        ```

        *Agent's Final Answer to User:*
        The capital of France is Paris. Its estimated population (city proper) is approximately 2.1 million as of early 2024."""
    )
