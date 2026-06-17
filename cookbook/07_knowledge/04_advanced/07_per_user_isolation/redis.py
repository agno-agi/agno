"""Per-user knowledge isolation with Redis (RediSearch).

Demonstrates the two halves of vector-DB isolation: Alice/Bob private
ownership plus an admin shared bucket.

How it works under the hood (Redis):

  * Each indexed document carries a ``user_id`` TAG field. The wrapper
    uses a ``\\x1f`` separator and ``case_sensitive=True`` so multi-
    character ids stay atomic.
  * Reads pass a RediSearch filter ``(@user_id:{alice}) | ismissing
    (@user_id)``. The ``ismissing`` clause makes shared content
    discoverable to scoped readers.
  * Owner tag values escape ``|`` so OIDC-style ids like ``auth0|alice``
    don't parse as tag-union.
  * ``user_id=None`` drops the predicate entirely.

Prerequisites:

  * Redis Stack (with RediSearch + RedisJSON) running locally::

        docker run -p 6379:6379 redis/redis-stack-server:latest

  * ``OPENAI_API_KEY`` set in your environment.

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/redis.py
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.redis import RedisDB
from agno.vectordb.search import SearchType


def _write_temp_doc(name: str, body: str) -> str:
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


async def main() -> None:
    vector_db = RedisDB(
        index_name="per_user_isolation_demo",
        redis_url="redis://localhost:6379",
        search_type=SearchType.vector,
    )
    try:
        await vector_db.async_drop()
    except Exception:
        pass
    await vector_db.async_create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (Redis)",
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
