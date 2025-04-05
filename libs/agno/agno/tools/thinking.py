from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class ThinkingTools(Toolkit):
    def __init__(
        self,
        think: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs,
    ):
        super().__init__(
            name="thinking_tools",
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        if instructions is None:
            self.instructions = dedent("""\
            ## Using the think tool
            Before taking any action or responding to the user after receiving tool results, use the think tool as a scratchpad to:
            - List the specific rules that apply to the current request
            - Check if all required information is collected
            - Verify that the planned action complies with all policies
            - Iterate over tool results for correctness

            ## Rules
            - Use the think tool generously to jot down thoughts and ideas.\
            """)

        if think:
            # Register the think tool
            self.register(self.think)

    def think(self, agent: Agent, thought: str) -> str:
        """Use the tool to think about something.
        It will not obtain new information or take any actions, but just append the thought to the log and return the result.
        Use it when complex reasoning or some cache memory or a scratchpad is needed.

        :param thought: A thought to think about and log.
        :return: The full log of thoughts and the new thought.
        """
        try:
            log_debug(f"Thought: {thought}")

            # Add the thought to the Agent state
            if agent.session_state is None:
                agent.session_state = {}
            if "thoughts" not in agent.session_state:
                agent.session_state["thoughts"] = []
            agent.session_state["thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in agent.session_state["thoughts"]])
            formatted_thoughts = dedent(
                f"""Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            logger.error(f"Error recording thought: {e}")
            return f"Error recording thought: {e}"
