"""Per-user knowledge isolation with MongoDB Atlas Vector Search.

Demonstrates the two halves of vector-DB isolation:

  1. Alice and Bob each upload their own private docs. RAG retrieval
     as Alice returns Alice's chunks plus shared content, never Bob's.

  2. Admin uploads org-wide content (no owner) → shared bucket visible
     to both.

How it works under the hood (MongoDB):

  * Every document carries a top-level ``user_id`` field. Shared content
    stores ``None``.
  * Atlas Vector Search uses an index ``filter`` clause so the predicate
    is evaluated alongside the ANN walk: ``{user_id: {$in: ["alice",
    null]}}``. The wrapper builds an ``$or`` of ``{user_id: X}`` and
    ``{user_id: None}`` so admin uploads remain discoverable.
  * ``user_id=None`` drops the predicate entirely (admin / unscoped view).

Prerequisites:

  * MongoDB with Atlas Vector Search support. Plain Community Edition
    Mongo (``mongo:7`` / ``mongo:8`` Docker images) does NOT support
    ``$vectorSearch`` — the server will reject the aggregation with::

        Using $search and $vectorSearch aggregation stages requires
        additional configuration. Please connect to Atlas or an
        AtlasCLI local deployment to enable.

    You have two options:

    A) **Atlas-Local Docker image** — the closest "just runs locally"
       experience. No auth, no replica-set setup, supports
       ``$vectorSearch`` out of the box::

        docker run -d -p 27017:27017 \\
          --name mongodb-container \\
          -v ./tmp/mongo-data:/data/db \\
          mongodb/mongodb-atlas-local:8.0.3

       Leave ``MONGODB_CONN_STRING`` unset — the cookbook default works.

    B) **Atlas cloud (free M0)** — sign up at mongodb.com/cloud/atlas,
       create a cluster, then::

        export MONGODB_CONN_STRING="mongodb+srv://USER:PASS@CLUSTER.mongodb.net/?retryWrites=true"

  * ``OPENAI_API_KEY`` set in your environment.

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/mongodb.py
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
    # Default assumes the Atlas-Local docker image (option A in the
    # docstring above) — no auth, standalone, $vectorSearch supported.
    "mongodb://localhost:27017/?directConnection=true",
)
DB_NAME = "agno_demo"
COLLECTION = "per_user_isolation_demo"


def _write_temp_doc(name: str, body: str) -> str:
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    vector_db = MongoDb(
        database=DB_NAME,
        collection_name=COLLECTION,
        db_url=MONGO_URI,
    )
    # Drop-and-recreate so the demo starts clean. In production you'd
    # migrate the schema instead.
    await vector_db.async_drop()
    await vector_db.async_create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (MongoDB)",
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
        # no user_id → shared bucket
    )

    print("\n=== Direct asearch tests ===\n")
    alice_salary = await knowledge.asearch(query="What is Alice's salary?", user_id="alice")
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    alice_about_bob = await knowledge.asearch(query="What is Bob's salary?", user_id="alice")
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")
    bob_chunks = [d for d in alice_about_bob if d.meta_data.get("user_id") == "bob"]
    assert not bob_chunks, "Isolation broken: Alice's retrieval surfaced Bob's chunks"
    print("  isolation holds: Bob's chunks are NOT visible to Alice")

    bob_holidays = await knowledge.asearch(query="When is the company closed?", user_id="bob")
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    admin_view = await knowledge.asearch(query="salary", user_id=None)
    print(f"\nAdmin asks about salary (user_id=None) -> {len(admin_view)} results")
    for d in admin_view:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

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
