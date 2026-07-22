"""
Per-User Knowledge Isolation with Milvus
========================================
Each user gets a private view of one shared knowledge base. Documents
uploaded with a user_id are visible only to that user; documents uploaded
without one are shared with everyone.

Milvus stores the owner in a nullable user_id scalar field and pushes
user_id == X or user_id is null into the search expression.

- Search as Alice: her chunks plus shared content, never Bob's
- Search as Bob: his chunks plus shared content, never Alice's
- Search with user_id=None: admin view, sees everything

Note: Milvus Lite (local-file uri) does not return dynamic scalar fields
on this read path, so retrieved content comes back empty and the demo
verifies isolation by result counts. A full Milvus server also returns
populated content with the same code.

Requirements: pip install "pymilvus[milvus-lite]" (embedded) and OPENAI_API_KEY
Run: python cookbook/07_knowledge/04_advanced/07_per_user_isolation/milvus_db.py
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.milvus import Milvus


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # Milvus Lite does not implement the async index-creation path, so
    # create the collection with the sync client.
    vector_db = Milvus(
        collection="per_user_isolation_demo",
        uri="/tmp/milvus_per_user_isolation.db",
    )
    vector_db.drop()
    vector_db.create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Milvus)",
        vector_db=vector_db,
    )

    # Alice and Bob upload private docs; the last upload has no user_id,
    # which makes it shared / org-wide content.
    await knowledge.ainsert(
        path=_write_temp_doc(
            "alice_salary.txt",
            "Alice's salary is $180,000. Reviewed annually in March.",
        ),
        name="alice_salary",
        user_id="alice",
    )

    await knowledge.ainsert(
        path=_write_temp_doc(
            "bob_salary.txt",
            "Bob's salary is $215,000. Reviewed annually in June.",
        ),
        name="bob_salary",
        user_id="bob",
    )

    await knowledge.ainsert(
        path=_write_temp_doc(
            "company_holidays.txt",
            "The company is closed on January 1, July 4, and December 25.",
        ),
        name="company_holidays",
    )

    print("\n=== Direct asearch tests ===\n")

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"Admin (user_id=None) -> {len(admin_view)} results (whole corpus)")

    alice_view = await knowledge.asearch(query="salary", user_id="alice")
    print(f"Alice (scoped)        -> {len(alice_view)} results (own + shared)")

    bob_view = await knowledge.asearch(query="salary", user_id="bob")
    print(f"Bob (scoped)          -> {len(bob_view)} results (own + shared)")

    # Count-based checks (see the Milvus Lite note in the module docstring):
    # each scoped view drops exactly the other user's private chunk.
    assert alice_view, "expected Alice's own results, got none"
    assert len(admin_view) == 3, (
        f"Admin should see the whole corpus, got {len(admin_view)}"
    )
    assert len(alice_view) == len(admin_view) - 1, (
        "Isolation broken: Alice's scoped view should drop exactly Bob's chunk"
    )
    assert len(bob_view) == len(admin_view) - 1, (
        "Isolation broken: Bob's scoped view should drop exactly Alice's chunk"
    )
    print("  isolation holds: neither user's scope includes the other's chunk")

    bob_holidays = await knowledge.asearch(
        query="When is the company closed?", user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    assert bob_holidays, "Bob should still see the shared holidays doc"

    print("\n=== Agent-mediated test ===\n")

    # The agent's user_id flows into run_context and scopes its retrieval.
    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.5"),
        knowledge=knowledge,
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

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
