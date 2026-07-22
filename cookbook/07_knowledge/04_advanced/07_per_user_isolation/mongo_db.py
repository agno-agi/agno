"""Per-user knowledge isolation with MongoDB.

Same isolation contract as the pgvector / Qdrant / Chroma cookbooks in this
directory, against a different backend. The ``Knowledge.asearch(user_id=...)``
API is identical — only the underlying primitive changes:

  * MongoDB Atlas stores the owner in a top-level ``user_id`` field (kept out
    of meta_data) that is declared as a ``filter`` field on the vector search
    index. Owned chunks carry the uploader's id; shared chunks store null.

  * Scoped reads push the owner predicate INTO the ``$vectorSearch`` stage as
    a pre-filter: ``{"$or": [{"user_id": "alice"}, {"user_id": null}]}`` —
    caller's bucket OR the shared bucket. Filtering before ranking keeps
    top-K recall correct.

  * When you pass ``user_id=None``, no predicate is added — the admin /
    debugging path sees everything.

Three uploads, four scoped queries:

  1. Alice and Bob each upload private content.
  2. An admin uploads org-wide content (``user_id`` left ``None``).
  3. Alice asks about Alice — sees her chunk plus shared content.
  4. Alice asks about Bob — sees ZERO bob chunks (assertion below).
  5. Bob asks about holidays — sees the shared bucket.
  6. Admin (``user_id=None``) sees everything.

Prerequisites:

  * A MongoDB Atlas-Local container (plain ``mongo`` has no ``$vectorSearch``)::

      docker run -d -p 27017:27017 mongodb/mongodb-atlas-local:latest

    Override the connection with ``MONGODB_CONN_STRING`` if it lives elsewhere.

  * ``OPENAI_API_KEY`` set in your environment (or swap the model below).

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/mongo_db.py
"""

import asyncio
import os
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.mongodb import MongoDb

MONGO_URI = os.getenv(
    "MONGODB_CONN_STRING",
    # Default assumes the Atlas-Local docker image — no auth, standalone.
    "mongodb://localhost:27017/?directConnection=true",
)
DB_NAME = "agno_demo"
COLLECTION = "per_user_isolation_demo"


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # Set up a Knowledge instance backed by MongoDB Atlas.
    # ------------------------------------------------------------------
    vector_db = MongoDb(
        database=DB_NAME,
        collection_name=COLLECTION,
        db_url=MONGO_URI,
        # Atlas-Local builds the vector index in the background; give it room.
        # Builds run slower when many other DB containers share the Docker VM.
        wait_until_index_ready_in_seconds=300,
    )

    # Build the collection + search index via the SYNC path. The rest of the
    # demo (ainsert / asearch) is async, but async_create's index-readiness
    # poll trips over the async driver cursor on Atlas-Local and stalls until
    # timeout. The sync create path is unaffected and produces the same index.
    # Drop-and-recreate so the demo starts clean; in production you'd migrate.
    vector_db.drop()
    vector_db.create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (MongoDB)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to the MongoDB
    # backend, which stamps it into the top-level ``user_id`` field.
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
        # No ``user_id`` — org-wide / admin-uploaded shared content. MongoDB
        # stores null in the ``user_id`` field; scoped queries match it via
        # the ``{"user_id": null}`` branch of the $vectorSearch pre-filter.
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
    # This backend keeps user_id internal (not surfaced in returned meta_data),
    # so verify isolation by content rather than by reading an owner off the row.
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
    # which the knowledge search reads and forwards to ``knowledge.search``.
    # In a real deployment this comes from ``get_scoped_user_id(request)``.
    # ------------------------------------------------------------------
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
