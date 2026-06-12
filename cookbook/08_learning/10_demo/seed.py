"""
Learning Demo: Seed Data
========================
Runs a few short conversations through the ops assistant so that every
Learning page in AgentOS has data: user profiles, user memories, session
context, entity memories, and decision logs.

Run:
    .venvs/demo/bin/python cookbook/08_learning/10_demo/seed.py

Then start the AgentOS server with run.py and connect from os.agno.com.
"""

from agents import ops_assistant

ALICE = "alice@vantagelabs.dev"
BEN = "ben@northwind.io"

# (user_id, session_id, message)
CONVERSATIONS = [
    # Alice: profile, preferences, and a session with a clear goal
    (
        ALICE,
        "alice-postgres-upgrade",
        "Hi, I'm Alice Chen, engineering lead at Vantage Labs. "
        "I prefer short, direct answers with code over prose.",
    ),
    (
        ALICE,
        "alice-postgres-upgrade",
        "My goal this week is to upgrade our Postgres cluster from version 15 "
        "to 17 with zero downtime. Help me plan the migration.",
    ),
    (
        ALICE,
        "alice-postgres-upgrade",
        "Some context: Marcus Lee is our infra engineer and owns the Postgres "
        "cluster. The cluster runs on Kubernetes in us-east-1.",
    ),
    (
        ALICE,
        "alice-postgres-upgrade",
        "Should we use logical replication or pg_upgrade for the cutover? "
        "Recommend one and log your decision.",
    ),
    # Ben: a second user with different preferences and entities
    (
        BEN,
        "ben-design-system",
        "Hey, I'm Ben Okafor, founder at Northwind. We closed our Series A "
        "round last week. I like detailed answers that walk through trade-offs.",
    ),
    (
        BEN,
        "ben-design-system",
        "We are kicking off the Design System project this quarter and Sarah "
        "Kim will lead it. What should the first milestone be? Pick one and "
        "log your decision.",
    ),
]

if __name__ == "__main__":
    for user_id, session_id, message in CONVERSATIONS:
        print()
        print("=" * 70)
        print(f"USER: {user_id} | SESSION: {session_id}")
        print("=" * 70)
        ops_assistant.print_response(
            message,
            user_id=user_id,
            session_id=session_id,
            stream=True,
        )

    # ------------------------------------------------------------------
    # Show what the agent learned
    # ------------------------------------------------------------------
    lm = ops_assistant.learning_machine

    print()
    print("=" * 70)
    print("WHAT THE AGENT LEARNED")
    print("=" * 70)

    for user_id in (ALICE, BEN):
        lm.user_profile_store.print(user_id=user_id)
        lm.user_memory_store.print(user_id=user_id)

    lm.session_context_store.print(session_id="alice-postgres-upgrade")
    lm.decision_log_store.print(agent_id="ops-assistant", limit=10)

    print()
    print("Entities discovered:")
    seen = set()
    for query in ("postgres", "northwind", "design"):
        for entity in lm.entity_memory_store.search(query=query, limit=5):
            if entity.entity_id not in seen:
                seen.add(entity.entity_id)
                print(f"- {entity.name} ({entity.entity_type})")

    print()
    print("Seed complete. Start the server and explore the Learning pages:")
    print("    .venvs/demo/bin/python cookbook/08_learning/10_demo/run.py")
