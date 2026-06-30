"""
Per-User Knowledge Isolation with Qdrant
========================================
Give each user a private view of one shared knowledge base. Documents a user
uploads are visible only to them; documents uploaded with no user are shared
with everyone, and an admin (no user id) sees all of it.

Qdrant does this by storing the owner as an indexed payload field and filtering
on it, using its multi-tenancy support to keep each user's vectors grouped.
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "per_user_isolation_demo"


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # In-memory Qdrant — zero infra to demo isolation. For production,
    # point ``location`` at your Qdrant Cloud or self-hosted URL.
    #
    # Important: Qdrant's sync and async clients are independent
    # instances. Under ``:memory:`` they get disjoint storage, and
    # against a local ``path=`` Qdrant takes a process-wide lock so only
    # one client can hold it. The whole demo path is async (Knowledge's
    # ``ainsert`` / ``asearch``), so we must create the collection via
    # the async client too — call ``async_create()``, NOT ``create()``.
    # ------------------------------------------------------------------
    vector_db = Qdrant(collection=COLLECTION_NAME, location=":memory:")
    await vector_db.async_create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Qdrant)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to the Qdrant
    # backend, which stamps it into the indexed payload field. The API
    # call is identical to pgvector / LanceDB / Chroma.
    # ------------------------------------------------------------------
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
        # No ``user_id`` — this is org-wide / admin-uploaded shared content.
        # Qdrant stores NULL in the payload; scoped queries match it via
        # IsEmptyCondition in the ``should`` branch of the filter.
    )

    # ------------------------------------------------------------------
    # Demonstrate the isolation contract DIRECTLY against Knowledge.
    # ------------------------------------------------------------------
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
    # The canonical isolation assertion: Bob's content must never surface
    # in Alice's retrieval, no matter how relevant it is to her query.
    bob_phrases = ["Bob's salary", "$215"]
    for d in alice_about_bob:
        for phrase in bob_phrases:
            assert phrase not in d.content, (
                f"Isolation broken: Alice's retrieval surfaced Bob's chunk "
                f"(matched {phrase!r}): {d.content!r}"
            )
    print("  isolation holds: Bob's chunks are NOT visible to Alice")

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

    # ------------------------------------------------------------------
    # End-to-end: an Agent doing RAG-as-Alice never sees Bob's chunks.
    # The ``user_id`` on the Agent flows into ``run_context.user_id``,
    # which ``KnowledgeTools.search_knowledge`` reads and forwards to
    # ``knowledge.search``. In a real deployment this comes from
    # ``get_scoped_user_id(request)`` (the JWT sub).
    # ------------------------------------------------------------------
    print("\n=== Agent-mediated test ===\n")

    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.4"),
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
