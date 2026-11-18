"""
Recency Boost: Surfacing Recently Updated Documents
===================================================
Vector search has no notion of time, so a superseded document ranks as well as the
revision that replaced it. RecencyReranker blends the search score with an exponential
decay on a timestamp, so an older document has to be clearly more relevant to outrank
a newer one.

It is a tilt, not a sort by date:
- weight=0.0 ranks by relevance alone
- weight=0.3 (the default) lets freshness break near-ties
- weight=1.0 ranks by age alone

half_life_days sets how fast the boost fades. This example uses a very short one so a
few seconds of age separate the documents; a real corpus wants days or weeks.

Set your own date under updated_at when adding content, and it is used first. Failing
that, PgVector built with return_updated_at=True reports when each row was stored, so
a document counts as fresh from when it entered the store and re-ingesting it under the
same name makes it fresh again. Stores reporting no timestamp leave ordering untouched.

Setup:
    ./cookbook/scripts/run_pgvector.sh

See also: 08_mmr_diverse_results.py for diversity reranking.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.recency import RecencyReranker
from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(
    table_name="recency_demo",
    db_url=db_url,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    # Report when each row was stored, so documents with no timestamp of their own still
    # have one to decay on. Off by default: it travels in metadata the model can see.
    return_updated_at=True,
)

# Start clean, so re-running does not stack copies from a previous run.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    vector_db=vector_db,
    reranker=RecencyReranker(
        # Seconds rather than days, so this example separates documents stored moments
        # apart. Use days or weeks against a real corpus.
        half_life_days=0.0001,
        # Recency against relevance: 0.0 is relevance alone, 1.0 age alone.
        weight=0.5,
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

POLICIES = [
    ("expenses-2019", "Expense policy: the daily limit is 50 USD. Approval by email."),
    (
        "expenses-2023",
        "Expense policy: the daily limit is 75 USD. Approval in the portal.",
    ),
    (
        "travel-2024",
        "Travel policy: book flights through the agency, economy class only.",
    ),
]

QUERY = "What is the daily expense limit?"


def show(label: str, results) -> None:
    print(label)
    for document in results:
        meta = document.meta_data or {}
        # The user's own date if it has one, else the row timestamp PgVector reports.
        stored = str(
            meta.get("updated_at") or meta.get(STORE_RECENCY_METADATA_KEY, "unknown")
        )[11:19]
        snippet = " ".join(document.content.split())[:58]
        print(f"  [{stored}] {document.name}: {snippet}...")
    print()


if __name__ == "__main__":

    async def main():
        for name, text in POLICIES:
            await knowledge.ainsert(text_content=text, name=name)
            await asyncio.sleep(1)

        plain = Knowledge(vector_db=vector_db)

        print("\n" + "=" * 64)
        print("PgVector + recency boost")
        print("=" * 64 + "\n")

        show("Relevance only", await plain.asearch(QUERY, max_results=3))
        show("With recency, as stored", await knowledge.asearch(QUERY, max_results=3))

        # The 2019 policy is revised. Re-ingesting under the same name replaces the stored
        # row rather than adding a second one, and the replacement is stored now, so the
        # revised policy becomes the freshest document.
        await asyncio.sleep(1)
        await knowledge.ainsert(
            text_content="Expense policy: the daily limit is 120 USD. Approval in the mobile app.",
            name="expenses-2019",
        )

        show(
            "After revising the 2019 policy",
            await knowledge.asearch(QUERY, max_results=3),
        )

        await agent.aprint_response(QUERY, stream=True)

    asyncio.run(main())
