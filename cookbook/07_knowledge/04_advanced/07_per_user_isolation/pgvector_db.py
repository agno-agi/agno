"""
Per-User Knowledge Isolation with PgVector
==========================================
Give each user a private view of one shared knowledge base. Documents a user
uploads are visible only to them; documents uploaded with no user are shared
with everyone, and an admin (no user id) sees all of it.

PgVector does this by storing each chunk's owner in a user_id column and
filtering on it at query time, so a search reads only that user's rows plus
the shared ones.

Setup: ./cookbook/scripts/run_pgvector.sh
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # Set up a Knowledge instance backed by pgvector.
    # ------------------------------------------------------------------
    vector_db = PgVector(table_name="per_user_isolation_demo", db_url=DB_URL)

    # Drop any pre-existing table so we start with the current schema. If
    # you ran an earlier version of this cookbook (or anything that
    # created the table before pgvector grew a ``user_id`` column), the
    # legacy table would lack that column and every row would look like
    # shared content to the new WHERE clause — isolation would silently
    # fail. Starting clean avoids that footgun. In production, run a real
    # migration; here we just drop-and-reingest.
    await vector_db.async_drop()
    await vector_db.async_create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to every chunk
    # written to pgvector — K2 stamps it onto ``meta_data["user_id"]``.
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
        # In pgvector the column stores NULL; scoped searches match it via
        # ``user_id = caller OR user_id IS NULL``. Other backends use
        # whatever primitive applies (shared collection, shared namespace,
        # etc.) — the cookbook API stays the same.
    )

    # ------------------------------------------------------------------
    # Demonstrate the isolation contract DIRECTLY against Knowledge.
    # ------------------------------------------------------------------
    print("\n=== Direct asearch tests ===\n")

    # 1. Alice asks about her own salary — she should find HER chunk.
    alice_salary = await knowledge.asearch(
        query="What is Alice's salary?", user_id="alice"
    )
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}")

    # 2. Alice asks about Bob — she should NOT see Bob's chunk. Best she can
    #    do is the shared holidays doc, which is unrelated.
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

    # 3. Bob asks about company holidays — he should see the SHARED chunk.
    bob_holidays = await knowledge.asearch(
        query="When is the company closed?", user_id="bob"
    )
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}")

    # 4. Admin / no scope passed — sees everything.
    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")

    # ------------------------------------------------------------------
    # End-to-end: an Agent doing RAG-as-Alice never sees Bob's chunks.
    # The ``user_id`` is threaded through Knowledge.asearch from whatever
    # caller (an OS router, a custom tool, your own code) decides the
    # right owner is. For this demo we pass it explicitly.
    # ------------------------------------------------------------------
    print("\n=== Agent-mediated test ===\n")

    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge,
        # Pin the agent to Alice's identity for retrieval. In a real
        # deployment this comes from JWT.sub / get_scoped_user_id(request).
        user_id="alice",
        instructions=[
            "Answer questions using ONLY the knowledge you can retrieve.",
            "If you don't know, say so — do not invent salary figures.",
        ],
        markdown=True,
    )

    response = await alice_agent.arun("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
