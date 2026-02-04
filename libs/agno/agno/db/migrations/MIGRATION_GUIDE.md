# Agno v2.5 Storage Migration Guide

## Overview

Agno v2.5 introduces **normalized storage** to address the O(N^2) storage growth issue that occurred when using `add_history_to_context=True` with high `num_history_runs` values.

### The Problem (v2.4 and earlier)

In previous versions, each run stored its complete message list including all previous history. Since each historical message already contained its own history, this created recursive duplication:

- Run 1: 2 messages
- Run 2: 2 + 2 = 4 messages (including history from Run 1)
- Run 3: 2 + 4 = 6 messages (including history from Runs 1-2)
- Run N: 2 + (N-1) * average_messages

This led to **quadratic storage growth** (O(N^2)), causing:
- Sessions reaching 100s of MB after 10-20 messages
- Database upsert failures when session size exceeded limits
- Poor performance when loading/saving sessions

### The Solution (v2.5+)

Normalized storage stores runs and messages in separate tables:
- `agno_runs`: One row per run (without messages)
- `agno_messages`: One row per message (linked to run)
- `agno_tool_calls`: One row per tool call (linked to message)

This achieves **linear storage growth** (O(N)):
- Each run stores only its own messages
- History is reconstructed via efficient SQL JOINs
- No data duplication

## Migration Options

### Option 1: Enable Normalized Storage for New Data (Recommended)

For new projects or when starting fresh, simply enable normalized storage:

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(db_url="postgresql://..."),
    add_history_to_context=True,
    num_history_runs=999,
    use_normalized_storage=True,  # Enable v2.5 normalized storage
)
```

The normalized tables will be created automatically on first use.

### Option 2: Migrate Existing Data

For existing databases with JSONB session data:

```python
from agno.db.postgres import PostgresDb
from agno.db.migrations import (
    estimate_migration,
    migrate_to_normalized_storage,
    verify_migration,
)

db = PostgresDb(db_url="postgresql://...")

# Step 1: Estimate the migration scope
estimate = estimate_migration(db)
print(f"Sessions to migrate: {estimate['total_sessions']}")
print(f"Estimated runs: {estimate['estimated_runs']}")
print(f"Estimated storage savings: {estimate['estimated_storage_savings_mb']} MB")

# Step 2: Run migration (dry run first)
stats = migrate_to_normalized_storage(db, dry_run=True)
print(f"Would migrate: {stats['runs_migrated']} runs, {stats['messages_migrated']} messages")

# Step 3: Run actual migration
stats = migrate_to_normalized_storage(
    db,
    batch_size=100,
    clear_jsonb_runs=False,  # Keep JSONB data as backup initially
)

# Step 4: Verify migration for specific sessions
result = verify_migration(db, session_id="your-session-id")
print(f"Runs match: {result['runs_match']}")
print(f"Messages match: {result['messages_match']}")

# Step 5: (Optional) Clear JSONB runs after verification
# Run migration again with clear_jsonb_runs=True to free up space
```

### Option 3: Immediate Workaround (v2.4.x)

If you can't upgrade to v2.5 yet, use this workaround:

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(db_url="postgresql://..."),
    add_history_to_context=True,
    num_history_runs=999,
    store_history_messages=False,  # Don't store history copies
)
```

This prevents the storage explosion but doesn't provide the full benefits of normalized storage.

## Breaking Changes

### API Changes

1. **`store_history_messages` behavior change**: When using `use_normalized_storage=True`, the `store_history_messages` flag is effectively always `False` for storage purposes (history is never duplicated in storage).

2. **`AgentSession.to_dict()` signature change**: Now accepts an optional `include_runs` parameter. When using normalized storage, runs are excluded by default.

3. **`AgentSession.from_dict()` signature change**: Now accepts optional `db` and `use_normalized_storage` parameters.

### Database Schema Changes

New tables are created alongside existing `agno_sessions`:

```sql
-- New tables (v2.5+)
agno_runs (run_id, session_id, agent_id, status, content, metrics, ...)
agno_messages (message_id, run_id, role, content, ...)
agno_tool_calls (tool_call_id, message_id, tool_name, tool_args, ...)
```

The existing `agno_sessions.runs` JSONB column is preserved for backward compatibility but can be cleared after migration.

### Behavioral Changes

1. **Lazy loading**: When using normalized storage, runs are loaded from the database on-demand rather than being embedded in the session object.

2. **History reconstruction**: `session.get_messages()` reconstructs history by querying the normalized tables, which is more efficient for large sessions.

3. **Direct database queries**: If you were querying the `runs` JSONB column directly, you'll need to update your queries to use the normalized tables or the session API.

## Performance Comparison

| Metric | v2.4 (JSONB) | v2.5 (Normalized) |
|--------|--------------|-------------------|
| Storage per 100 runs | O(N^2) ~50MB+ | O(N) ~500KB |
| Load session | Deserialize entire blob | Lazy load on demand |
| Get last N messages | Load all, filter in Python | SQL LIMIT query |
| Insert new run | Rewrite entire session | Single INSERT |

## Troubleshooting

### Migration fails with timeout

For very large sessions, increase the batch size or migrate specific sessions:

```python
migrate_to_normalized_storage(
    db,
    batch_size=10,  # Smaller batches
    session_ids=["specific-session-id"],  # Migrate specific sessions
)
```

### Runs not loading after migration

Ensure you've enabled normalized storage on your agent:

```python
agent = Agent(
    # ...
    use_normalized_storage=True,
)
```

### Session size still large after migration

Run migration with `clear_jsonb_runs=True` to remove the JSONB data:

```python
migrate_to_normalized_storage(
    db,
    clear_jsonb_runs=True,  # Clear JSONB after migration
)
```

## Support

For issues with the migration, please open an issue on GitHub with:
- Agno version
- Database type and version
- Error messages
- Session size estimates
