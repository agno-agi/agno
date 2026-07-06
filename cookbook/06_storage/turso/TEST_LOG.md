# Turso Cookbook Test Log

### turso_for_agent.py

**Status:** PASS

**Description:** Sanity-check that `TursoDb(url=..., auth_token=...)` constructs correctly and that `Agent` writes session/run history to a remote Turso database. Validated end-to-end against `libsql://playground-*.aws-ap-northeast-1.turso.io` during development: `_create_all_tables`, `upsert_session` (insert + ON CONFLICT update), `get_session`, `rename_session`, `upsert_user_memory`, `get_user_memories` all succeed.

**Result:** Sessions and runs are persisted to the remote Turso database; subsequent runs read prior history via `add_history_to_context=True`.

---
