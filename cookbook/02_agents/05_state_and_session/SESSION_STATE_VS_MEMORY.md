# Session State vs Memory

Agno provides two ways to persist information across agent runs. They look similar but solve different problems.

## Quick comparison

| | Session state | User memory |
|---|---|---|
| **Scope** | One session (conversation) | One user across all sessions |
| **Key** | `session_id` | `user_id` |
| **Typical data** | Shopping lists, workflow steps, UI mode | Preferences, facts, audit notes |
| **Who writes it** | Your code, tools, or `enable_agentic_state` | `MemoryManager`, `update_memory_on_run`, or `enable_agentic_memory` |
| **Survives new session** | No (unless you copy values yourself) | Yes |
| **In context by default** | When referenced in `instructions` or `add_session_state_to_context=True` | When memory is enabled on the agent |

## When to use session state

Use session state for **working data** tied to the current conversation:

- A todo list the agent is building during this chat
- Temporary counters, flags, or form fields
- Tool factories that pick different tools based on `session_state["mode"]`

See: `session_state_basic.py`, `agentic_session_state.py`, `02_session_state_tools.py`

## When to use memory

Use memory for **durable user knowledge** that should follow the person:

- "I prefer Python over JavaScript"
- Compliance rulings or support notes from prior cases
- Profile fields learned over many conversations

See: `../06_memory_and_learning/memory_manager.py`, `cookbook/11_memory/01_agent_with_memory.py`

## Common combinations

Many production agents use **both**:

1. **Session state** holds the current task (cart items, draft document, step index).
2. **Memory** holds user-level facts the agent should remember next week.
3. **Chat history** (via `db`) stores the raw messages for this session.

They are complementary, not interchangeable.

## Decision checklist

Choose **session state** if:

- The data should reset when the user starts a new chat.
- Tools need a mutable dict the agent updates during the run.
- Multiple users share one agent instance but have separate sessions.

Choose **memory** if:

- The data should appear in a future session with a new `session_id`.
- You need user-scoped facts, preferences, or audit trails.
- You want the agent (or `MemoryManager`) to decide what to remember.

## Related examples

| Topic | Location |
|---|---|
| Session state basics | `session_state_basic.py` |
| Cross-session user facts | `../06_memory_and_learning/memory_manager.py` |
| Session summaries (compress chat) | `session_summary.py` |
| Search old sessions | `search_session_history.py` |