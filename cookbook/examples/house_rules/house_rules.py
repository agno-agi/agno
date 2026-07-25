"""
House Rules
===========
Write down the three routing rules your team learned the hard way, then measure what
they are worth. The same agent routes the same four tickets twice: once against an
empty knowledge base, once after the rules have been inserted into it.

Nothing changes between the two runs except the rows in the vector database, so the
environment fingerprint is identical and the two pass rates are comparable. You will
see about 0.25 before and 1.00 after, plus a per-task diff of exactly what moved.

Running this file measures both runs and exits: 32 live model calls, about 20
seconds. There is no server here, so this folder is one file.
"""

import asyncio

from agno.agent import Agent
from agno.environments import Environment, Task, arun_rollouts
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from agno.vectordb.chroma import ChromaDb
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# The rules and what counts as correct
# ---------------------------------------------------------------------------
HOUSE_RULES = """Refunds above 500 USD go to escalations. Billing handles refunds of 500 USD or less.
A charge the customer's bank has already reversed goes to fraud. Billing never touches a reversed charge.
Accounts less than 14 days old go to onboarding, no matter what the customer is asking about."""


class Routing(BaseModel):
    queue: str


def routed_correctly(run, expected) -> bool:
    return isinstance(run.content, Routing) and run.content.queue == expected


# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
# The rules live as rows in a vector database you own. The collection starts empty,
# which is what makes the first run an honest before.
knowledge = Knowledge(vector_db=ChromaDb(collection="house_rules"))

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    knowledge=knowledge,
    # Retrieve on every run and paste the hits into the prompt, so the rules reach
    # the model on a fixed path.
    add_knowledge_to_context=True,
    search_knowledge=False,
    output_schema=Routing,
    instructions="Route the ticket to one queue: billing, escalations, fraud, onboarding, or support.",
)

# ---------------------------------------------------------------------------
# The environment: four tickets, one scorer
# ---------------------------------------------------------------------------
env = Environment(
    name="ticket-routing",
    agent=agent,
    scorer=CodeScorer(routed_correctly),
    tasks=(
        Task(
            id="big-refund",
            input="The customer wants 900 USD back on their annual plan.",
            expected="escalations",
        ),
        Task(
            id="chargeback",
            input="The customer's bank has already reversed last month's charge.",
            expected="fraud",
        ),
        Task(
            id="new-account",
            input="A customer who signed up two days ago was charged twice for their 40 USD monthly plan.",
            expected="onboarding",
        ),
        # The control: the agent already gets this one right, and the rules must not
        # break it.
        Task(
            id="loud-overcharge",
            input="The customer is threatening to post about a 700 USD overcharge on social media.",
            expected="escalations",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Run: measure, insert the rules, measure again
# ---------------------------------------------------------------------------
async def main() -> None:
    before = await arun_rollouts(env, k=4)

    await knowledge.ainsert(name="house-rules", text_content=HOUSE_RULES)

    after = await arun_rollouts(env, k=4)

    print()
    print(f"pass rate without the rules: {before.pass_rate:.2f}")
    print(f"pass rate with the rules:    {after.pass_rate:.2f}")
    print()
    # diff() refuses to compare two runs whose env fingerprints differ, so a printed
    # diff is itself proof that the tasks, the scorer, and the prompt were held fixed.
    print(after.diff(before))


if __name__ == "__main__":
    # Both runs share one event loop, so the model's async client outlives the first
    # rollout batch.
    asyncio.run(main())
