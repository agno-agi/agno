"""
Force Context Compaction Test

Uses a very low token limit to force compaction to trigger.
This verifies the full compaction flow works end-to-end.

Run: .venvs/demo/bin/python cookbook/14_context_compaction/05_force_compaction.py
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Low message limit to force compaction
MESSAGE_LIMIT = 4

db = SqliteDb(db_file="tmp/force_compaction_test.db")

# Create compaction manager with low limits to force compaction
# Model is required for token counting
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),
    compact_context=True,
    compact_context_message_limit=4,  # Trigger after 4 messages
    compact_context_keep_recent=2,  # Only keep 2 recent messages
)

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-mini"),
    session_id="force-compaction-test",
    db=db,
    add_history_to_context=True,  # Include previous turns in context
    compaction_manager=compaction_manager,
    markdown=True,
    debug_mode=False,
)

print(f"Testing context compaction with {MESSAGE_LIMIT} message limit")
print("=" * 60)

# These prompts will generate long responses that exceed the token limit
prompts = [
    "My name is Alice and I'm a software engineer working on distributed systems. Remember this.",
    "Explain the CAP theorem in detail with examples of systems that prioritize each property.",
    "Now explain the PACELC theorem and how it extends CAP.",
    "What are the trade-offs between consistency and availability in my distributed system design?",
    "Based on our conversation, what would you recommend for a system that needs high availability?",
    "What was my name and profession again?",  # Test if user info survives compaction
]

last_response = None
for i, prompt in enumerate(prompts, 1):
    print(f"\n--- Turn {i} ---")
    print(f"User: {prompt[:60]}...")

    response = agent.run(prompt)
    last_response = response

    # Check compaction state after each turn
    state = response.compaction_state
    if state and state.total_compactions > 0:
        print(
            f"[COMPACTION #{state.total_compactions}] {state.total_tokens_saved} tokens saved"
        )

    print(f"Assistant: {response.content[:150]}...")

print("\n" + "=" * 60)
print("Final compaction state:")
if last_response and last_response.compaction_state:
    state = last_response.compaction_state
    print(f"  Total compactions: {state.total_compactions}")
    print(f"  Messages compacted: {state.compacted_count}")
    print(f"  Total tokens saved: {state.total_tokens_saved}")
    print("\nSummary preview:")
    print(state.summary[:500] + "..." if len(state.summary) > 500 else state.summary)
else:
    print("  No compaction occurred")
