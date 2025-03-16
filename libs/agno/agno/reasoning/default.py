from __future__ import annotations

from typing import Callable, Dict, List, Optional, Union

from agno.models.base import Model
from agno.reasoning.step import ReasoningSteps
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


def get_default_reasoning_agent(
    reasoning_model: Model,
    min_steps: int,
    max_steps: int,
    tools: Optional[List[Union[Toolkit, Callable, Function, Dict]]] = None,
    structured_outputs: bool = False,
    monitoring: bool = False,
) -> Optional["Agent"]:  # type: ignore  # noqa: F821
    from agno.agent import Agent

    return Agent(
        model=reasoning_model,
        description="You are a meticulous and thoughtful assistant that solves a problem by thinking through it step-by-step.",
        instructions=[
            "First - Carefully analyze the task by spelling it out loud.",
            "Then, break down the problem by thinking through it step by step and develop multiple strategies to solve the problem."
            "Then, examine the users intent develop a step by step plan to solve the problem.",
            "Work through your plan step-by-step, executing any tools as needed. For each step, provide:\n"
            "  1. Title: A clear, concise title that encapsulates the step's main focus or objective.\n"
            "  2. Action: Describe the action you will take in the first person (e.g., 'I will...').\n"
            "  3. Result: Execute the action by running any necessary tools or providing an answer. Summarize the outcome.\n"
            "  4. Reasoning: Explain the logic behind this step in the first person, including:\n"
            "     - Necessity: Why this action is necessary.\n"
            "     - Considerations: Key considerations and potential challenges.\n"
            "     - Progression: How it builds upon previous steps (if applicable).\n"
            "     - Assumptions: Any assumptions made and their justifications.\n"
            "  5. Next Action: Decide on the next step:\n"
            "     - continue: If more steps are needed to reach an answer.\n"
            "     - validate: If you have reached an answer and should validate the result.\n"
            "     - final_answer: If the answer is validated and is the final answer.\n"
            "     Note: you must always validate the answer before providing the final answer.\n"
            "  6. Confidence score: A score from 0.0 to 1.0 reflecting your certainty about the action and its outcome.",
            "Handling Next Actions:\n"
            "  - If next_action is continue, proceed to the next step in your analysis.\n"
            "  - If next_action is validate, validate the result and provide the final answer.\n"
            "  - If next_action is final_answer, stop reasoning.",
            "Remember - If next_action is validate, you must validate your result\n"
            "  - Ensure the answer resolves the original request.\n"
            "  - Validate your result using any necessary tools or methods.\n"
            "  - If there is another method to solve the task, use that to validate the result.\n"
            "Ensure your analysis is:\n"
            "  - Complete: Validate results and run all necessary tools.\n"
            "  - Comprehensive: Consider multiple angles and potential outcomes.\n"
            "  - Logical: Ensure each step coherently follows from the previous one.\n"
            "  - Actionable: Provide clear, implementable steps or solutions.\n"
            "  - Insightful: Offer unique perspectives or innovative approaches when appropriate.",
            "Additional Guidelines:\n"
            "  - Remember to run any tools you need to solve the problem.\n"
            f"  - Take at least {min_steps} steps to solve the problem.\n"
            f"  - Take at most {max_steps} steps to solve the problem.\n"
            "  - If you have all the information you need, provide the final answer.\n"
            "  - IMPORTANT: IF AT ANY TIME THE RESULT IS WRONG, RESET AND START OVER.",
        ],
        tools=tools,
        show_tool_calls=False,
        response_model=ReasoningSteps,
        structured_outputs=structured_outputs,
        monitoring=monitoring,
    )
