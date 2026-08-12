"""
Per-User Isolation: Cassandra
=============================
Each user gets a private view of one shared knowledge base. Documents uploaded
with a user_id are visible only to that user, documents uploaded without one are
shared with everyone, and a search with no user_id is the admin view.

Cassandra stores the owner in each chunk's metadata, marks shared chunks with
a __shared__ sentinel, and searches the caller's and the shared bucket.

Requirements:
- ./cookbook/scripts/run_cassandra.sh
- uv pip install cassandra-driver cassio
- OPENAI_API_KEY
"""

import asyncio
from typing import List

import cassio
from agno.agent import Agent
from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.cassandra import Cassandra
from cassandra.cluster import Cluster

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

ALICE_SALARY = "Alice's salary is $180,000. Reviewed annually in March."
BOB_SALARY = "Bob's salary is $215,000. Reviewed annually in June."
HOLIDAYS = "The company is closed on January 1, July 4, and December 25."

CASSANDRA_HOST = "localhost"
CASSANDRA_PORT = 9042
KEYSPACE = "per_user_demo"
TABLE_NAME = "per_user_isolation_demo"


def show(label: str, results: List[Document]) -> None:
    """Print one search result set."""
    print(f"{label} -> {len(results)} results")
    for d in results:
        print(f"  - {d.content[:80]}")
    print()


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------

# The keyspace has to exist before cassio can attach to it.
cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
session = cluster.connect()
session.execute(
    f"CREATE KEYSPACE IF NOT EXISTS {KEYSPACE} "
    "WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}"
)
cassio.init(session=session, keyspace=KEYSPACE)

# The Cassandra backend fixes its vector column at 1024 dimensions.
vector_db = Cassandra(
    table_name=TABLE_NAME,
    keyspace=KEYSPACE,
    session=session,
    embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1024),
)

# Start clean: rows left by an earlier run still carry their owner and would
# show up as extra results below.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    name="per_user_demo",
    description="Per-user RAG isolation demo (Cassandra)",
    vector_db=vector_db,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main() -> None:
        await knowledge.ainsert(
            name="alice_salary",
            text_content=ALICE_SALARY,
            user_id="alice",
        )
        await knowledge.ainsert(
            name="bob_salary",
            text_content=BOB_SALARY,
            user_id="bob",
        )
        # The last insert has no user_id, which makes it shared content.
        await knowledge.ainsert(
            name="company_holidays",
            text_content=HOLIDAYS,
        )

        print("\n" + "=" * 60)
        print("SCOPED SEARCH: three callers, one corpus")
        print("=" * 60 + "\n")

        alice_view = await knowledge.asearch(query="salary", user_id="alice")
        show("Alice (user_id='alice')", alice_view)
        alice_text = " ".join(d.content for d in alice_view)
        assert "180,000" in alice_text, "Alice cannot retrieve her own document"
        assert "January 1" in alice_text, (
            "Shared content is unreachable from Alice's scoped view"
        )
        assert "215,000" not in alice_text, (
            "Isolation broken: Alice's scoped view leaked Bob's salary"
        )

        bob_view = await knowledge.asearch(query="salary", user_id="bob")
        show("Bob (user_id='bob')", bob_view)
        bob_text = " ".join(d.content for d in bob_view)
        assert "215,000" in bob_text, "Bob cannot retrieve his own document"
        assert "January 1" in bob_text, (
            "Shared content is unreachable from Bob's scoped view"
        )
        assert "180,000" not in bob_text, (
            "Isolation broken: Bob's scoped view leaked Alice's salary"
        )

        admin_view = await knowledge.asearch(query="salary", user_id=None)
        show("Admin (user_id=None)", admin_view)
        admin_text = " ".join(d.content for d in admin_view)
        for expected in ("180,000", "215,000", "January 1"):
            assert expected in admin_text, (
                f"Admin view is missing {expected}, it has to see every owner"
            )
        assert all(d.content in admin_text for d in alice_view), (
            "Admin view has to be a superset of a scoped user's view"
        )
        print("Alice and Bob each see their own chunk plus the shared one.")
        print("Admin sees the whole corpus.")

        print("\n" + "=" * 60)
        print("AGENT-MEDIATED RETRIEVAL: the owner has to survive the handoff")
        print("=" * 60 + "\n")

        alice_agent = Agent(
            name="Alice's Assistant",
            model=OpenAIResponses(id="gpt-5.5"),
            knowledge=knowledge,
            search_knowledge=True,
            user_id="alice",
            instructions=[
                "Answer questions using ONLY the knowledge you can retrieve.",
                "If you don't know, say so - do not invent salary figures.",
            ],
            markdown=True,
        )

        response = await alice_agent.arun("What is Bob's salary?")
        print("Alice's agent on 'What is Bob's salary?':")
        print(response.content)

        # Assert on what retrieval returned, not on the model's prose.
        retrieved = " ".join(
            item["content"]
            for ref in (response.references or [])
            for item in (ref.references or [])
            if isinstance(item, dict) and item.get("content")
        )
        assert retrieved, (
            "Retrieval returned no documents, so the isolation check below would pass on nothing"
        )
        assert "215,000" not in retrieved, (
            "Isolation broken: Alice's agent retrieved Bob's salary. The owner was "
            "dropped between the run context and the vector DB, so retrieval ran "
            "unscoped (user_id=None, the admin view)."
        )
        print("\nisolation holds: Bob's salary never reached Alice's agent")
        print("\nDone.")
        cluster.shutdown()

    asyncio.run(main())
