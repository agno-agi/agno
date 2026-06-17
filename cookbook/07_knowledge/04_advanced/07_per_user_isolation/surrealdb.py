"""Per-user knowledge isolation with SurrealDB.

Demonstrates the two halves of vector-DB isolation: Alice/Bob private
ownership plus an admin shared bucket.

How it works under the hood (SurrealDB):

  * Each record stores a ``user_id`` field. Shared content stores
    ``NONE``.
  * Reads bind a dedicated ``$scope_user_id`` parameter (separate from
    any caller-supplied ``user_id`` filter so they can't collide):
    ``WHERE (user_id = $scope_user_id OR user_id = NONE)``.
  * The record id folds in ``user_id`` so two users' identical content
    won't clobber each other.
  * ``user_id=None`` drops the predicate entirely.

Prerequisites:

  * SurrealDB running locally::

        docker run -p 8000:8000 surrealdb/surrealdb:latest \\
          start --user root --pass root memory

  * ``OPENAI_API_KEY`` set in your environment.

Run:

    python cookbook/07_knowledge/04_advanced/07_per_user_isolation/surrealdb.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.surrealdb import SurrealDb
from surrealdb import Surreal


def _write_temp_doc(name: str, body: str) -> str:
    p = Path(f"/tmp/{name}")
    p.write_text(body)
    return str(p)


def main() -> None:
    client = Surreal(url="ws://localhost:8000/rpc")
    client.signin({"username": "root", "password": "root"})
    client.use("agno", "demo")

    vector_db = SurrealDb(
        client=client,
        collection="per_user_isolation_demo",
    )
    try:
        vector_db.drop()
    except Exception:
        pass
    vector_db.create()

    knowledge = Knowledge(
        name="per_user_demo",
        description="Per-user RAG isolation demo (SurrealDB)",
        vector_db=vector_db,
    )

    knowledge.insert(
        path=_write_temp_doc(
            "alice_salary.txt",
            "Alice's salary is $180,000. Reviewed annually in March.",
        ),
        name="alice_salary",
        user_id="alice",
    )
    knowledge.insert(
        path=_write_temp_doc(
            "bob_salary.txt",
            "Bob's salary is $215,000. Reviewed annually in June.",
        ),
        name="bob_salary",
        user_id="bob",
    )
    knowledge.insert(
        path=_write_temp_doc(
            "company_holidays.txt",
            "The company is closed on January 1, July 4, and December 25.",
        ),
        name="company_holidays",
    )

    print("\n=== Direct search tests ===\n")
    alice_salary = knowledge.search(query="What is Alice's salary?", user_id="alice")
    print(f"Alice asks about Alice's salary -> {len(alice_salary)} results")
    for d in alice_salary:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    alice_about_bob = knowledge.search(query="What is Bob's salary?", user_id="alice")
    print(f"\nAlice asks about Bob's salary -> {len(alice_about_bob)} results")
    for d in alice_about_bob:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")
    bob_chunks = [d for d in alice_about_bob if d.meta_data.get("user_id") == "bob"]
    assert not bob_chunks, "Isolation broken: Alice's retrieval surfaced Bob's chunks"
    print("  isolation holds: Bob's chunks are NOT visible to Alice")

    bob_holidays = knowledge.search(query="When is the company closed?", user_id="bob")
    print(f"\nBob asks about holidays -> {len(bob_holidays)} results")
    for d in bob_holidays:
        print(f"  - {d.content[:80]}  (owner={d.meta_data.get('user_id')!r})")

    admin_view = knowledge.search(query="salary", user_id=None)
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
    response = alice_agent.run("What is Bob's salary?")
    print("Alice's agent on 'What is Bob's salary?':")
    print(response.content)
    print("\nDone.")


if __name__ == "__main__":
    main()
