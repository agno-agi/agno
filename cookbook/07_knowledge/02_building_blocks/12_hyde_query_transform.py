"""
HyDE: Searching With a Hypothetical Answer
==========================================
Questions and the passages that answer them rarely share wording. "Why did revenue
drop?" has almost nothing in common with "Q3 declined due to churn in enterprise
accounts", so the question embeds some distance from its own answer.

HyDE asks an LLM to invent an answer and searches with that instead. The invented
passage never reaches the user and does not need to be correct: it only has to look
like the kind of document being searched for, which lands it closer to real answers.

The reranker still scores against the question as asked, so relevance is judged on what
the user wanted rather than on a stand-in for it.

Costs one LLM call per search. If that call fails the original query is used, so a
provider outage degrades results rather than breaking search.

model defaults to the agent's own model, so it only needs setting to use a cheaper or
faster one for the generation step.

Setup:
    ./cookbook/scripts/run_pgvector.sh

See also: 08_mmr_diverse_results.py for reranking after the search.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.query_transform.hyde import HyDE
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(
    table_name="hyde_demo",
    db_url=db_url,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# Start clean, so re-running does not stack copies from a previous run.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    vector_db=vector_db,
    query_transform=HyDE(),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

# The first note uses the words of the question without answering it; the second
# answers it without using them. Searching with the question favours the first.
NOTES = [
    (
        "revenue-policy",
        "This document explains how revenue is recognised, and when a drop in revenue "
        "must be reported to the finance committee.",
    ),
    (
        "q3-review",
        "Enterprise renewals slipped last quarter as three large accounts delayed "
        "signing, and churn in the mid market ran higher than forecast.",
    ),
    (
        "hiring",
        "Headcount grew by 40, concentrated in the platform and support teams.",
    ),
]

QUERY = "Why did revenue drop?"


def show(label: str, results) -> None:
    print(label)
    for document in results:
        snippet = " ".join(document.content.split())[:70]
        print(f"  {document.name}: {snippet}...")
    print()


if __name__ == "__main__":

    async def main():
        for name, text in NOTES:
            await knowledge.ainsert(text_content=text, name=name)

        print("\n" + "=" * 64)
        print("PgVector + HyDE")
        print("=" * 64 + "\n")

        plain = Knowledge(vector_db=vector_db)
        show("Searching with the question", await plain.asearch(QUERY, max_results=3))

        # Generates a hypothetical answer, then searches with that.
        show(
            "Searching with a hypothetical answer",
            await knowledge.asearch(QUERY, max_results=3),
        )

        await agent.aprint_response(QUERY, stream=True)

    asyncio.run(main())
