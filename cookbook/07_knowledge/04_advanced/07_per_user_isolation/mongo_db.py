"""
Per-User Isolation: MongoDB
===========================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone. Searching with user_id=None is the
admin view and sees the whole corpus.

MongoDB stores the owner in a top-level user_id field declared as a filter
field on the vector index, and pre-filters $vectorSearch on caller OR null.

Plain MongoDB has no $vectorSearch, so this needs an Atlas-Local container.

Requirements:
- docker run -d -p 27017:27017 mongodb/mongodb-atlas-local:latest
- uv pip install pymongo
- OPENAI_API_KEY
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.mongodb import MongoDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

ALICE_SALARY = "Alice's salary is $180,000. Reviewed annually in March."
BOB_SALARY = "Bob's salary is $215,000. Reviewed annually in June."
HOLIDAYS = "The company is closed on January 1, July 4, and December 25."

MONGO_URI = "mongodb://localhost:27017/?directConnection=true"
DB_NAME = "agno_demo"
COLLECTION_NAME = "per_user_isolation_demo"


def show(label: str, results: List[Document]) -> None:
    """Print one search result set."""
    print(f"{label} -> {len(results)} results")
    for d in results:
        print(f"  - {d.content[:80]}")
    print()


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------

vector_db = MongoDb(
    database=DB_NAME,
    collection_name=COLLECTION_NAME,
    db_url=MONGO_URI,
    # Atlas-Local builds the vector index in the background; give it room.
    wait_until_index_ready_in_seconds=300,
)

# Drop and recreate: a stale index would not declare user_id as a filter field.
# Sync path, not async_create: its readiness poll stalls on Atlas-Local.
if vector_db.exists():
    vector_db.drop()
vector_db.create()

knowledge = Knowledge(
    name="per_user_demo",
    description="Per-user RAG isolation demo (MongoDB)",
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
        # The last upload has no user_id, which makes it shared content.
        await knowledge.ainsert(
            name="company_holidays",
            text_content=HOLIDAYS,
        )

        # $vectorSearch reads a background index, so a fresh write is not searchable yet.
        await asyncio.sleep(10)

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

    asyncio.run(main())
