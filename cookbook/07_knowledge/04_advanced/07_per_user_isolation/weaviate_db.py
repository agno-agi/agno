"""Per-user knowledge isolation with Weaviate.

Same isolation contract as the pgvector / Qdrant / Chroma cookbooks in
this directory, against a different backend. The
``Knowledge.asearch(user_id=...)`` API is identical — only the underlying
primitive changes:

  * Weaviate stores the owner as a text property ``user_id`` on each
    object. Owned chunks carry the uploader's id; shared chunks carry no
    owner.

  * Scoped reads compile to a Weaviate ``Filter`` of the form
    ``user_id == caller OR user_id IS NULL`` — the caller's bucket plus
    the shared bucket. Passing ``user_id=None`` adds no owner predicate,
    so the admin / debugging path sees everything.

Three uploads, four scoped queries:

  1. Alice and Bob each upload private content.
  2. An admin uploads org-wide content (``user_id`` left ``None``).
  3. Alice asks about Alice — sees her chunk plus shared content.
  4. Alice asks about Bob — sees ZERO bob chunks (assertion below).
  5. Bob asks about holidays — sees the shared bucket.
  6. Admin (``user_id=None``) sees everything.

Prerequisites:

  * Weaviate running locally. From the repo root::

      ./cookbook/scripts/run_weaviate.sh

  * ``OPENAI_API_KEY`` set in your environment (or swap the model below).

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/weaviate_db.py
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.weaviate import Distance, VectorIndex, Weaviate


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    vector_db = Weaviate(
        collection="per_user_isolation_demo",
        vector_index=VectorIndex.HNSW,
        distance=Distance.COSINE,
        local=True,
    )
    await vector_db.async_drop()
    await vector_db.async_create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Weaviate)",
        vector_db=vector_db,
    )

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
    alice_salary = await knowledge.asearch(
        query="What is Alice's salary?", user_id="alice"
    )
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}")

    alice_about_bob = await knowledge.asearch(
        query="What is Bob's salary?", user_id="alice"
    )
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}")
    # This backend keeps user_id internal (not surfaced in returned meta_data),
    # so verify isolation by content rather than by reading an owner off the row.
    bob_leak = [d for d in alice_about_bob if "215,000" in d.content]
    assert not bob_leak, "Isolation broken: Alice's retrieval surfaced Bob's salary"
    print("  isolation holds: Bob's salary is NOT visible to Alice")

    bob_holidays = await knowledge.asearch(
        query="When is the company closed?", user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}")

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")

    print("\n=== Agent-mediated test ===\n")
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
