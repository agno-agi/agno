"""Per-user knowledge isolation with ChromaDB.

Same isolation contract as the pgvector / LanceDB cookbooks in this
directory, against a different backend. The
``Knowledge.asearch(user_id=...)`` API is identical — only the underlying
primitive changes.

Chroma uses its **native multi-tenancy primitive: one collection per
tenant.** That's the vendor-recommended pattern for tenant isolation —
chunks for Alice physically live in a different collection from chunks
for Bob, so a query against Alice's collection cannot return Bob's
content. This is materially simpler than (and immune to) the metadata
filter quirks that other backends have.

How it works under the hood:

  * Insert with ``user_id="alice"`` → write to ``{table}__alice``.
  * Insert with ``user_id=None``     → write to ``{table}`` (the BASE
    collection, which doubles as the shared / org-wide bucket).
  * Search with ``user_id="alice"``  → query BOTH ``{table}__alice``
    AND ``{table}``, merge results by distance, take top ``limit``.
  * Search with ``user_id=None``     → query only the BASE collection
    (admin / unscoped view of shared content).

One difference from pgvector / LanceDB worth noting: those backends
return ALL rows when you search with ``user_id=None`` because they're
filtered SQL-style. Chroma's model is collection-based, so
``user_id=None`` only sees the BASE / shared collection — not every
user's content. To audit across users, iterate explicitly per user_id.

Prerequisites:

  * ``pip install chromadb`` (embedded — no server to run).
  * ``OPENAI_API_KEY`` set in your environment (or swap the model below).

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/chromadb.py
"""

import asyncio
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.chroma import ChromaDb

DB_PATH = "/tmp/agno_per_user_isolation_chromadb"
COLLECTION_NAME = "per_user_isolation_demo"


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # Wipe any previous on-disk state. If you ran an older version of
    # this cookbook (before Chroma grew per-user collection routing),
    # the cached collection layout could be inconsistent. In production
    # you'd run a real migration; here we just drop-and-reingest.
    # ------------------------------------------------------------------
    if Path(DB_PATH).exists():
        shutil.rmtree(DB_PATH)

    vector_db = ChromaDb(collection=COLLECTION_NAME, path=DB_PATH)

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (ChromaDB)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to the Chroma
    # backend, which routes each insert to its per-user collection.
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
        # No ``user_id`` — this is org-wide / admin-uploaded shared
        # content. Chroma routes it to the BASE collection; scoped
        # searches read it alongside the caller's own collection.
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
    # The canonical isolation assertion. The collection model makes this
    # physically guaranteed (Bob's chunks aren't even in the collections
    # we queried) — but we still assert at the cookbook level so any
    # regression would crash here, loudly.
    for d in alice_about_bob:
        for phrase in ["Bob's salary", "$215"]:
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

    # ``user_id=None`` on Chroma sees the BASE/shared collection only
    # (unlike pgvector/LanceDB where None means "no scope, all rows").
    admin_view = await knowledge.asearch(query="anything", user_id=None)
    print(f"\nAdmin asks about everything (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}")

    # ------------------------------------------------------------------
    # End-to-end: an Agent doing RAG-as-Alice never sees Bob's chunks.
    # ``run_context.user_id`` flows from the Agent into Knowledge.asearch,
    # which routes to Alice's collection plus the shared one.
    # ------------------------------------------------------------------
    print("\n=== Agent-mediated test ===\n")

    alice_agent = Agent(
        name="Alice's Assistant",
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge,
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
