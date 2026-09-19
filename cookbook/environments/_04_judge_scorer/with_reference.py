"""
Judge Against a Reference
=========================

Put a reference answer in Task.expected. JudgeScorer receives it as fenced
comparison data, so free-form answers can be checked for semantic agreement.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions=(
        "Solve the chained calculation. Explain the intermediate product, digit "
        "sum, and remainder briefly, then state one unambiguous final integer."
    ),
)

environment = Environment(
    name="reference-answer-judge",
    agent=agent,
    tasks=(
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add its decimal digits, multiply the sum by 131071, subtract "
                "the product remainder modulo 65521, and return the result."
            ),
            expected="The final integer is 20944939.",
            id="reference-chain-a",
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. "
                "Add its decimal digits, multiply the sum by 104729, subtract "
                "the product remainder modulo 65537, and return the result."
            ),
            expected="The final integer is 16731173.",
            id="reference-chain-b",
        ),
    ),
    scorer=JudgeScorer(
        model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
        criteria=(
            "Pass only if the output's final integer agrees exactly with the "
            "reference answer and the output does not state a contradictory "
            "final result. Intermediate prose may differ."
        ),
        mode="binary",
    ),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
