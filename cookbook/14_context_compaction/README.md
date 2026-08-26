# Context Compaction

Automatic context compression for long conversations. When context approaches limits, older assistant/tool messages are summarized while user messages are preserved verbatim.

## Why Context Compaction?

Long conversations exceed model context windows. Traditional solutions have drawbacks:
- **Truncation** loses important early context
- **Session summaries** are additive (summary + full history)
- **Tool compression** only handles tool outputs

Context compaction solves this by:
1. Preserving user messages (intent, corrections, preferences)
2. Summarizing assistant/tool messages (work done, results)
3. Persisting state across session reloads

## Quick Start

```python
from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Create compaction manager with settings
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),  # Model for token counting and summaries
    compact_context=True,
    compact_context_message_limit=6,      # Trigger after 6 messages
    compact_context_keep_recent=2,        # Keep 2 recent messages uncompacted
)

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-mini"),
    db=SqliteDb(db_file="tmp/demo.db"),
    session_id="demo",
    add_history_to_context=True,
    compaction_manager=compaction_manager,
)

# Long conversations automatically compress when needed
for question in many_questions:
    response = agent.run(question)
    if response.compaction_state:
        print(f"Compacted: {response.compaction_state.total_tokens_saved} tokens saved")
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `compaction_manager` | None | CompactionManager instance with settings |

### CompactionManager Options

```python
from agno.compression import CompactionManager

cm = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),  # Required for token counting
    compact_context=True,                  # Enable context compaction
    compact_context_message_limit=6,       # Trigger after N messages
    compact_context_token_limit=10000,     # OR trigger after N tokens
    compact_context_keep_recent=2,         # Messages to keep uncompacted
    compact_context_preserve_user_budget=20000,  # Max user tokens to preserve
    compact_context_instructions="...",    # Custom summary prompt
)
```

**Key settings:**
- `model` - Required for token counting. Can be a cheap model like gpt-4.1-mini.
- `compact_context_keep_recent` - Default is 10. Set lower (2-4) for demos.
- `compact_context_message_limit` - Trigger based on message count.
- `compact_context_token_limit` - Trigger based on token count.

## Examples

| File | Description |
|------|-------------|
| `01_quickstart.py` | Basic usage with automatic compaction |
| `02_custom_model.py` | Use a cheap model for summaries |
| `03_with_tools.py` | Tool-heavy workflows |
| `04_with_session.py` | Persistent sessions with compaction state |
| `05_force_compaction.py` | Force compaction with low limits |
| `06_preference_survival.py` | Test that user preferences survive |
| `07_comprehensive_test.py` | Full test suite |
| `08_streaming_test.py` | Streaming responses |
| `09_multi_model_test.py` | Multi-provider configurations |

## How It Works

When context exceeds the limit:

1. **Split messages** into system, old, preserved users, and recent
2. **Keep recent** messages uncompacted (controlled by `keep_recent`)
3. **Summarize** old assistant/tool messages
4. **Rebuild context**: `[system] + [summary] + [preserved users] + [recent]`
5. **Store state** in `response.compaction_state`

The summary includes a prefix telling the model it's continuing from a compacted context.

## Accessing Compaction State

```python
response = agent.run("...")

if response.compaction_state:
    state = response.compaction_state
    print(f"Total compactions: {state.total_compactions}")
    print(f"Messages compacted: {state.compacted_count}")
    print(f"Tokens saved: {state.total_tokens_saved}")
    print(f"Summary: {state.summary[:200]}")
```

## Tips

1. **Use OpenAIChat** for demos - OpenAIResponses uses server-side context and won't trigger local compaction.
2. **Set `keep_recent` low** for testing - default 10 means you need many messages to see compaction.
3. **Add a model** to CompactionManager - required for token counting.
4. **Use `add_history_to_context=True`** - needed for messages to accumulate.
