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

This needs a real Milvus server. Milvus Lite (the local-file uri) drops the
scalar fields on the search read path, so retrieved content comes back empty
and the content checks below cannot run against it.

Requirements: a Milvus standalone server on localhost:19530 and OPENAI_API_KEY
  curl -sfL https://raw.githubusercontent.com/milvus-io/milvus/master/scripts/standalone_embed.sh -o standalone_embed.sh
  bash standalone_embed.sh start
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
    # Start clean: a collection created before the user_id field was declared
    # keeps its old schema, and there scoped reads never match shared chunks.
    vector_db = Milvus(
        collection="per_user_isolation_demo",
        uri="http://localhost:19530",
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

    alice_view = await knowledge.asearch(query="salary", user_id="alice")
    print(f"Alice (scoped) -> {len(alice_view)} results")
    for d in alice_view:
        print(f"  - {d.content[:80]}")

    alice_text = " ".join(d.content for d in alice_view)
    assert "180,000" in alice_text, (
        "Alice's own chunk came back without content - is this a Milvus server, or Milvus Lite?"
    )
    assert "January 1" in alice_text, (
        "Isolation broken: the shared holidays chunk is unreachable from Alice's scoped view"
    )
    assert "215,000" not in alice_text, (
        "Isolation broken: Alice's scoped view leaked Bob's salary"
    )
    print("  Alice sees her own chunk plus the shared one, and not Bob's")

    bob_view = await knowledge.asearch(query="salary", user_id="bob")
    print(f"\nBob (scoped) -> {len(bob_view)} results")
    for d in bob_view:
        print(f"  - {d.content[:80]}")

    bob_text = " ".join(d.content for d in bob_view)
    assert "215,000" in bob_text, "expected Bob's own results, got none"
    assert "January 1" in bob_text, (
        "Isolation broken: the shared holidays chunk is unreachable from Bob's scoped view"
    )
    assert "180,000" not in bob_text, (
        "Isolation broken: Bob's scoped view leaked Alice's salary"
    )
    print("  Bob sees his own chunk plus the shared one, and not Alice's")

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"\nAdmin (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")

    admin_text = " ".join(d.content for d in admin_view)
    for expected in ("180,000", "215,000", "January 1"):
        assert expected in admin_text, (
            f"Admin view should see the whole corpus, missing {expected}"
        )
    print("  Admin sees the whole corpus")

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
