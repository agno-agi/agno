"""
Context Compaction with Session Persistence

Compaction state is stored in session_data, allowing it to persist
across session reloads. This enables long-running conversations that
span multiple process restarts.

Run: .venvs/demo/bin/python cookbook/14_context_compaction/04_with_session.py
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Use SQLite for session persistence
db = SqliteDb(db_file="tmp/compaction_demo.db")

# Create compaction manager
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),
    compact_context=True,
    compact_context_message_limit=4,
    compact_context_keep_recent=2,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-mini"),
    session_id="compaction-demo-session",
    db=db,
    add_history_to_context=True,
    compaction_manager=compaction_manager,
    markdown=True,
)

print("Session-persistent context compaction demo")
print(f"Session ID: {agent.session_id}")
print("-" * 50)

# Run multiple turns
responses = [
    agent.run("Remember: my favorite color is blue and I work as a data scientist."),
    agent.run("What programming languages should I learn for my job?"),
    agent.run("Tell me more about Python libraries for data science."),
    agent.run(
        "What was my favorite color again?"
    ),  # Tests if user preference survives compaction
]

for i, r in enumerate(responses, 1):
    print(f"\nTurn {i}: {r.content[:150]}...")
    if r.compaction_state and r.compaction_state.total_compactions > 0:
        print(
            f"  [Compaction #{r.compaction_state.total_compactions}] {r.compaction_state.total_tokens_saved} tokens saved"
        )

# Check compaction state from last response
last_response = responses[-1]
state = last_response.compaction_state
if state and state.total_compactions > 0:
    print("\nFinal compaction state:")
    print(f"  Total compactions: {state.total_compactions}")
    print(f"  Messages compacted: {state.compacted_count}")
    print(f"  Tokens saved: {state.total_tokens_saved}")
else:
    print("\nNo compaction occurred (context stayed under limit)")
