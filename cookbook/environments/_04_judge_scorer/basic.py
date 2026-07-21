"""
JudgeScorer - Basic
===================

Use a binary LLM judge when the requirement is qualitative rather than an
exact field comparison. The judge applies one written rubric to every attempt.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions=(
        "Rewrite each customer-support draft. Acknowledge the customer's "
        "specific concern, apologize when appropriate, preserve every stated "
        "fact, remain concise, and end with one concrete next step. Do not "
        "claim the underlying problem is resolved. Give the company-owned next "
        "step a concrete follow-up window; a process-update commitment such as "
        "within two business days is allowed."
    ),
)

rubric = (
    "Pass only if all of these hold: (1) the first sentence acknowledges the "
    "specific customer impact, not generic frustration; (2) the reply includes "
    "one direct apology; (3) every amount, identifier, date, and stated status "
    "is preserved exactly; (4) the final sentence gives one action owned by the "
    "company and a concrete follow-up window; (5) it invents no resolution, "
    "cause, refund approval, or carrier promise. A vague offer to help fails."
)

environment = Environment(
    name="binary-support-judge",
    agent=agent,
    tasks=(
        Task(
            id="refund-delay",
            input=(
                "Draft: We received the $42.50 refund request for order A-1001 "
                "on 2026-07-14. Finance is still reviewing it."
            ),
        ),
        Task(
            id="lost-edits",
            input=(
                "Draft: The 2026-07-14 outage erased two days of edits. We "
                "restored the 2026-07-12 backup and applied a 20% credit. "
                "Engineering has not identified the cause."
            ),
        ),
    ),
    scorer=JudgeScorer(
        model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
        criteria=rubric,
        mode="binary",
    ),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}, "
            f"learning_zone={task_result.in_learning_zone}"
        )
