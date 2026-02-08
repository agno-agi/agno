# Prompt to test: `cookbook/06_storage`

Use this prompt with an AI coding agent to test and validate the storage cookbook.

---

Goal: Thoroughly test and validate `cookbook/06_storage` so it aligns with our cookbook standards.

Context files (read these first):
- `CLAUDE.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for postgres examples)

Execution requirements:
1. Spawn a parallel agent for each subdirectory under `cookbook/06_storage/`. Each agent handles one subdirectory independently.
2. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/06_storage/<SUBDIR>` and fix any violations.
   b. Run all `*.py` files in that subdirectory using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Make only minimal, behavior-preserving edits where needed for style compliance.
   e. Update `cookbook/06_storage/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file.
3. Also test root-level files (`01_persistent_session_storage.py`, `02_session_summary.py`, `03_chat_history.py`) and update `cookbook/06_storage/TEST_LOG.md`.
4. After all agents complete, collect and merge results.

Special cases:
- `postgres/` and `postgres_async/` require a running PostgreSQL instance (`./cookbook/scripts/run_pgvector.sh`).
- `mysql/` and `mysql_async/` require a running MySQL instance — skip if MySQL is not available.
- `mongo/` and `mongo_async/` require a running MongoDB instance — skip if MongoDB is not available.
- `redis/` requires a running Redis instance — skip if Redis is not available.
- `dynamodb/` requires AWS DynamoDB (local or cloud) — skip if not available.
- `firestore/`, `gcs/` require Google Cloud credentials — skip if not available.
- `surrealdb/` requires a running SurrealDB instance — skip if not available.
- `sqlite/`, `json_db/`, `in_memory/` have no external dependencies — these should always pass.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/06_storage/<SUBDIR>` (for each subdirectory)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `postgres` | `session_storage.py` | PASS | Session persisted and retrieved |
| `dynamodb` | `dynamodb_storage.py` | SKIP | DynamoDB not available locally |
