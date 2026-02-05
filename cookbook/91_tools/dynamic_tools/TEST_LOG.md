# TEST_LOG - Dynamic Tools Cookbooks

Test results for callable tools examples.

Last updated: 2026-02-05

## Test Environment

- Python: `.venvs/demo/bin/python` (via `direnv exec .` to load `.envrc`)
- Model: `gpt-4o-mini` (OpenAI)

---

## 01_user_namespaced_tools.py

**Status:** PASS

**Description:** Demonstrates per-user DuckDB isolation using callable tools. Each user gets their own database file.

**Result:** Successfully creates per-user database paths (e.g., `/tmp/user_dbs_xxx/alice/user_data.db`). Tools are resolved at runtime with the correct user_id.

---

## 02_multi_tenant_tools.py

**Status:** PASS

**Description:** Multi-tenant SaaS pattern where each tenant (organization) gets isolated tool resources.

**Result:** Successfully creates tenant-specific database paths based on `dependencies["tenant_id"]`, with isolation enforced via `callable_tools_cache_key`. Proper tenant isolation at the tool level.

---

## 03_session_scoped_tools.py

**Status:** PASS

**Description:** Per-session ephemeral databases. Each conversation session gets its own isolated database.

**Result:** Successfully creates session-scoped databases using `run_context.session_id`, with isolation enforced via `callable_tools_cache_key`. Data is isolated between sessions.

---

## 04_conditional_tools.py

**Status:** PASS

**Description:** Role-based tool access. Different roles (viewer/user/admin) get different tool capabilities.

**Result:**
- Viewer: Only gets `safe_calculator`
- User: Gets `safe_calculator` + `duckdb_tools`
- Admin: Gets all tools including admin operations

Tools are correctly filtered based on role from `session_state`.

---

## 05_combined_dynamic_resources.py

**Status:** PASS

**Description:** Combines callable knowledge AND callable tools for complete per-user isolation.

**Result:** Each user gets both their own ChromaDB collection (knowledge) and DuckDB database (tools). Complete data isolation at both storage layers.

---

## 06_api_key_scoped_tools.py

**Status:** PASS

**Description:** Tools configured with per-user API credentials from dependencies.

**Result:** Successfully creates tools with user-specific API keys. Premium tier users get additional tools. API key masking works correctly.

---

## Notes

- All cookbooks require `OPENAI_API_KEY` for the agent's model
- DuckDB tools require `duckdb` (`VIRTUAL_ENV=.venvs/demo uv pip install duckdb`)
- Cookbook 05 requires `chromadb` (`VIRTUAL_ENV=.venvs/demo uv pip install chromadb`)
- API errors (401) in test output are expected when `OPENAI_API_KEY` is not set
