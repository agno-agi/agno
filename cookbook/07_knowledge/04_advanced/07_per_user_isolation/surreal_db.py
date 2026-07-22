"""Per-user knowledge isolation with SurrealDB.

Same isolation contract as the pgvector / Qdrant / Chroma cookbooks in
this directory, against a different backend. The
``Knowledge.asearch(user_id=...)`` API is identical — only the underlying
primitive changes:

  * The SurrealDB table has a top-level ``user_id`` field typed
    ``option<string>``. Owned chunks carry the uploader's id; shared
    chunks store ``NONE``.

  * Scoped reads compile to a server-side predicate appended to the
    vector search: ``AND (user_id = $scope_user_id OR user_id = NONE)`` —
    the caller's own rows OR the shared bucket. The owner is bound as
    ``$scope_user_id`` so a caller's metadata filter can't collide with
    the scope.

  * When you pass ``user_id=None``, no owner predicate is added — the
    admin / debugging path. Admins see everything.

Three uploads, four scoped queries:

  1. Alice and Bob each upload private content.
  2. An admin uploads org-wide content (``user_id`` left ``None``).
  3. Alice asks about Alice — sees her chunk plus shared content.
  4. Alice asks about Bob — sees ZERO bob chunks (assertion below).
  5. Bob asks about holidays — sees the shared bucket.
  6. Admin (``user_id=None``) sees everything.

Prerequisites:

  * SurrealDB running locally. From the repo root::

      ./cookbook/scripts/run_surrealdb.sh

  * ``OPENAI_API_KEY`` set in your environment (or swap the model below).

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/surreal_db.py
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.surrealdb import SurrealDb
from surrealdb import AsyncSurreal, Surreal

COLLECTION_NAME = "per_user_isolation_demo"


def _write_temp_doc(name: str, body: str) -> str:
    """Write a tiny text file we can ingest. Returns the absolute path."""
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    # ------------------------------------------------------------------
    # Set up a Knowledge instance backed by SurrealDB. The demo path is
    # async (Knowledge's ``ainsert`` / ``asearch``), but SurrealDB's sync
    # and async connections are independent objects, and Knowledge's
    # constructor runs a synchronous ``exists()`` / ``create()``. So we
    # hand the backend BOTH: a blocking client for the constructor and an
    # async client for the async reads and writes below.
    # ------------------------------------------------------------------
    client = Surreal("ws://localhost:8000/rpc")
    client.signin({"username": "root", "password": "root"})
    client.use("agno", "demo")

    async_client = AsyncSurreal("ws://localhost:8000/rpc")
    await async_client.signin({"username": "root", "password": "root"})
    await async_client.use("agno", "demo")

    vector_db = SurrealDb(
        client=client, async_client=async_client, collection=COLLECTION_NAME
    )

    # Drop any pre-existing table so we start with the current schema. A
    # legacy table created before SurrealDB grew a ``user_id`` field would
    # make every row look like shared content and isolation would silently
    # fail. In production, run a real migration; here we drop-and-reingest.
    # SurrealDB's REMOVE TABLE errors if the table isn't there, so on the
    # first run we swallow that.
    try:
        await vector_db.async_drop()
    except Exception:
        pass
    await vector_db.async_create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (SurrealDB)",
        vector_db=vector_db,
    )

    # ------------------------------------------------------------------
    # Three uploads: Alice (private), Bob (private), Admin (shared).
    # The ``user_id`` kwarg on ``ainsert`` flows through to the SurrealDB
    # backend, which stamps it onto the row's ``user_id`` field. The API
    # call is identical to pgvector / Qdrant / Chroma.
    #
    # The default upsert path binds each reader-assigned UUID id via
    # ``UPSERT type::record($table, $record_id)`` and folds the owner into
    # the id, so identical content from two owners never collides.
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
        # SurrealDB stores NONE in the ``user_id`` field; scoped queries
        # match it via the ``user_id = NONE`` branch of the scope predicate.
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
    # in Alice's retrieval, no matter how relevant it is to her query. This
    # backend keeps user_id in a top-level field (not in returned meta_data),
    # so we assert on content rather than reading an owner off the row.
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
