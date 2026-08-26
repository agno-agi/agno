"""
Context Compaction Quickstart
=============================

Long conversations exceed model context windows. Context compaction solves this
by summarizing old assistant/tool messages while preserving user messages
(intent, corrections, preferences) verbatim.

When context approaches the limit, older messages are replaced with a summary.
The model sees: [system] + [summary] + [preserved users] + [recent messages].
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# CompactionManager needs a model for token counting
# keep_recent=2 means only 2 recent messages stay uncompacted (rest get summarized)
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),
    compact_context=True,
    compact_context_message_limit=6,
    compact_context_keep_recent=2,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-mini"),
    db=SqliteDb(db_file="tmp/quickstart_compaction.db"),
    session_id="quickstart-demo",
    add_history_to_context=True,
    compaction_manager=compaction_manager,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting multi-turn conversation...")

    responses = [
        agent.run(
            "What is Python? Give a detailed explanation with history and use cases."
        ),
        agent.run("Now explain JavaScript in the same level of detail."),
        agent.run("Compare Python and JavaScript for web development."),
        agent.run("What about TypeScript? How does it relate to JavaScript?"),
        agent.run("Can you summarize the key differences between all three languages?"),
    ]

    for i, response in enumerate(responses, 1):
        print(f"\n--- Turn {i} ---")
        print(
            response.content[:200] + "..."
            if len(response.content) > 200
            else response.content
        )

        if (
            response.compaction_state
            and response.compaction_state.total_compactions > 0
        ):
            print(
                f"  [Compaction #{response.compaction_state.total_compactions}] {response.compaction_state.total_tokens_saved} tokens saved"
            )

    # Final state
    last = responses[-1]
    if last.compaction_state and last.compaction_state.total_compactions > 0:
        state = last.compaction_state
        print(
            f"\nFinal: {state.total_compactions} compactions, {state.total_tokens_saved} tokens saved"
        )
