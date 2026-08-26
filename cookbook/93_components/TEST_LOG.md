# TEST_LOG.md - 93 Components Cookbook

Test results for `cookbook/93_components/` examples.

**Test Date:** 2026-02-08  
**Environment:** `.venvs/demo/bin/python`

---

## Structure Validation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validates cookbook structure for all Python files under `cookbook/93_components/` recursively.

**Result:** `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive` reported `Checked 14 file(s) ... Violations: 0`.

---

## Runtime Validation

### auto_populate_registry.py

**Status:** PASS

**Description:** Builds a team (two agents with distinct models, one with a custom tool and a db) and a workflow, hands them to AgentOS without an explicit registry, and prints the auto-populated registry. Runs offline (no model calls).

**Result:** Discovered `OpenAI:gpt-5.4` (collected once though shared by two agents), `OpenAI:gpt-5.4-mini`, the `get_weather` tool, and the `auto-registry-db` database. No registry was passed.

---

### auto_populate_registry_os.py

**Status:** PASS

**Description:** Same setup served as an AgentOS app. Verified `get_app()` builds and the registry is auto-populated; the components are served at `GET /registry?resource_type=...`. Constructed without serving (no blocking run).

**Result:** Registry contained the member agents' models and tool with no registry passed. App built successfully.

---

### user_isolation_os.py

**Status:** PASS

**Description:** Serves an AgentOS with `AuthorizationConfig(user_isolation=True)` and no code-defined components, so every agent/team/workflow is DB-backed and owner-scoped. Driven over HTTP against a real uvicorn server on Postgres with two JWTs (`alice`, `bob`).

**Result:** `POST /components` as alice returned 201 with `user_id: "alice"`. As bob, `GET /components` returned `total_count: 0`, `GET /agents` returned `[]`, and `GET /components/{alice_id}` returned 404, while alice still saw her component on both. 7/7 assertions passed.

**Note:** An `agno_components` table created before the `user_id` column was added fails with `Table ai.agno_components has an invalid schema`. Adding the column (`ALTER TABLE ... ADD COLUMN user_id VARCHAR`) is what the deferred migration will do; fresh databases are unaffected.

---
