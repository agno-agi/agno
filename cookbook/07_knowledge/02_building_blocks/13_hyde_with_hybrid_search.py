"""
HyDE With Hybrid Search
=======================
Hybrid search runs two retrievals and merges them: a vector half that matches on
meaning, and a keyword half that matches literal words. Both halves are given the same
query string.

include_query=True searches with the question and the invented passage together.

This example also sets model explicitly. Generating the passage does not need the model
answering the question, and a smaller one is usually enough for a few sentences of
plausible prose.

Setup:
    ./cookbook/scripts/run_pgvector.sh

See also: 12_hyde_query_transform.py for HyDE against plain vector search.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.query_transform.hyde import HyDE
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(
    table_name="hyde_hybrid_demo",
    db_url=db_url,
    search_type=SearchType.hybrid,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# Start clean, so re-running does not stack copies from a previous run.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    vector_db=vector_db,
    query_transform=HyDE(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        # Keep the question in the search string, so the keyword half of hybrid search
        # still matches on the words the user actually typed.
        include_query=True,
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

NOTES = [
    (
        "refund-policy",
        "This policy explains when a refund request is approved and which team owns the "
        "decision for orders above the standard threshold.",
    ),
    (
        "q3-support-review",
        "Customers waited an average of six days for money back last quarter because "
        "approvals queued behind a single reviewer in the billing team.",
    ),
    (
        "shipping",
        "Orders ship within two business days, and tracking is emailed once the carrier "
        "scans the parcel.",
    ),
]

QUERY = "Why are refunds slow?"


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
        print("PgVector hybrid search + HyDE")
        print("=" * 64 + "\n")

        plain = Knowledge(vector_db=vector_db)
        show("Searching with the question", await plain.asearch(QUERY, max_results=3))
        show("With HyDE, question kept", await knowledge.asearch(QUERY, max_results=3))

        # The search string itself is what the flag changes, so print it: the ranking
        # above may well be identical on a corpus this small.
        transformed = await knowledge.query_transform.atransform(
            QUERY, model=agent.model
        )
        print("Searched with:")
        print(f"  {' '.join(transformed.split())[:150]}...\n")

        await agent.aprint_response(QUERY, stream=True)

    asyncio.run(main())
