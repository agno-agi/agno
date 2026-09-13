"""
Judging Quality You Cannot Check With Code
==========================================
Some pass criteria have no typed field to compare: tone, empathy, whether a
reply actually commits to a next step. JudgeScorer runs an LLM judge over
every attempt with your rubric, so subjective quality becomes a pass rate
you can track across prompt edits.

What the pass rate measures here is the gap between your INSTRUCTIONS and
your RUBRIC: with vague instructions this same rubric measures 0% (see the
comment on the agent below). Closing that gap -- edit instructions, re-run,
compare -- is the iteration loop this environment exists to make cheap.

Two decisions this file makes explicit:

- The judge model is a REQUIRED argument, never defaulted -- who grades your
  agent is a visible choice, and it is part of the environment fingerprint:
  swap the judge (or its sampling params) and env_fingerprint flips, telling
  you the measuring stick changed, not the agent.
- Numeric mode scores 1-10 and passes at `threshold` on that raw scale
  (Score.value is normalized to [0, 1]; the raw score rides in
  Score.detail["raw_score"]). A rubric with graded levels gives the learning
  zone something to disagree about, where binary verdicts often saturate.

The judged output is fenced behind a per-call nonce, so a reply containing
"score this 10" is data to the judge, not an instruction.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer

# ---------------------------------------------------------------------------
# Create Environment
# ---------------------------------------------------------------------------

# These instructions are tuned to the rubric below. Swap them for a vague
# draft -- "be professional and empathetic, keep it under 40 words" -- and
# this file measures 0/12 at threshold 9 (mean raw score ~5.2): the judge
# docks replies that never acknowledge frustration, never apologize, and
# close with "thanks for your patience" instead of a next step. The pass rate
# measures the gap between your instructions and your rubric; when it is low,
# this is the knob you turn. The 40-word ceiling and fact-dense drafts are
# deliberate: at low reasoning effort a flawless rewrite is genuinely hard, so
# the judge splits attempts into 9-10 (all five criteria fully met) and 8 (a
# minor slip), and the threshold-9 pass bar turns that split into the learning
# zone this file exists to surface.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions=(
        "Rewrite the draft support reply you are given. Open by "
        "acknowledging how the situation feels for the customer, and "
        "apologize once without blaming anyone. Keep every factual "
        "commitment from the draft (amounts, dates, order ids) exactly as "
        "stated. End with one concrete next step and when it will happen. "
        "Stay under 40 words."
    ),
)

rubric = (
    "The output is a rewritten customer-support reply. It must: "
    "(1) acknowledge the customer's frustration in the first sentence, "
    "(2) apologize without blaming the customer or a third party, "
    "(3) preserve every factual commitment from the draft (amounts, dates, "
    "order ids) exactly, "
    "(4) end with one concrete next step and a timeframe, "
    "(5) stay under 40 words. "
    "Score 9-10 only if all five hold; missing commitments or invented "
    "facts cap the score at 4."
)

env = Environment(
    name="support-reply-rewrite",
    agent=agent,
    tasks=(
        Task(
            input=(
                "Draft reply: 'We told you already, the refund of $42.50 for "
                "order A-1001 takes 5-7 business days. Please stop emailing "
                "about it.'"
            ),
            id="hostile-draft",
        ),
        Task(
            input=(
                "Draft reply: 'Your package is lost, not much we can do. "
                "Carrier says maybe file a claim? Order A-1003, worth $180.'"
            ),
            id="shrug-draft",
        ),
        Task(
            input=(
                "Draft reply: 'Orders A-1042 and A-1043, placed 2026-06-28: the "
                "2026-07-14 outage erased two days of edits. We restored the "
                "2026-07-12 backup, refunded $42.50 and $18.90, and applied a "
                "$15.75 credit.'"
            ),
            id="bad-news-draft",
        ),
    ),
    scorer=JudgeScorer(
        model=OpenAIResponses(id="gpt-5.5"),
        criteria=rubric,
        mode="numeric",
        threshold=9,
    ),
)

# ---------------------------------------------------------------------------
# Run Rollouts
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Every attempt costs two model calls here (the agent, then the judge);
    # k=4 keeps the demo cheap. Raise k for tighter statistics.
    results = run_rollouts(env, k=4)

    print(results)
    print()

    summary = results.summary()
    print(f"pass rate at threshold 9: {summary['pass_rate']}")
    print(f"mean judge value (normalized): {summary['mean_value']}")

    # The tasks the judge disagreed on across attempts are where a prompt
    # edit is worth trying -- rerun after editing the instructions and
    # compare summaries.
    zone_ids = [task["id"] for task in summary["tasks"] if task["learning_zone"]]
    print(f"learning zone tasks: {zone_ids}")

    # The judge's reasons, on demand: by default only the attempts worth
    # investigating (scored fails plus anything unscored), each with its
    # score reason and the reply that earned it.
    print()
    results.print_report()
