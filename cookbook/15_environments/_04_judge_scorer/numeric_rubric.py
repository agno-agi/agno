"""
Numeric Judge Rubric
====================

Use a 1-10 rubric for graded quality and set an explicit pass threshold. The
API learning_zone() reports score-value variation here; this file separately
prints the true partial pass-rate rows where 0 < pass_rate < 1.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions=(
        "Rewrite each support draft in no more than 80 words. Open by naming "
        "the customer's concrete impact, apologize once, preserve all stated "
        "facts, and close with a company-owned next step and follow-up window. "
        "Do not claim an unresolved issue is fixed."
    ),
)

rubric = (
    "Score the reply from 1 to 10. Award two points each for: a specific impact "
    "acknowledgment in the opening sentence; exactly one direct apology; exact "
    "preservation of every fact; a final company-owned action with a concrete "
    "follow-up window; and no invented cause, status, approval, or resolution. "
    "A material factual change caps the raw score at 4."
)

environment = Environment(
    name="numeric-support-judge",
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
        mode="numeric",
        threshold=9,
    ),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()

    score_variation_ids = [
        task_result.task.id for task_result in results.learning_zone().task_results
    ]
    partial_pass_rate_ids = [
        task_result.task.id
        for task_result in results.task_results
        if task_result.pass_rate is not None and 0 < task_result.pass_rate < 1
    ]
    print(f"score-variation zone: {score_variation_ids}")
    print(f"true partial pass-rate rows: {partial_pass_rate_ids}")
    for task_result in results.task_results:
        values = [
            attempt.score.value for attempt in task_result.attempts if attempt.score
        ]
        print(
            f"{task_result.task.id}: normalized_values={values}, "
            f"pass_rate={task_result.pass_rate}"
        )
