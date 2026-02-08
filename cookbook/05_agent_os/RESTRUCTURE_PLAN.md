# Restructuring Plan: `cookbook/05_agent_os/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 28 (up to 5 levels deep) |
| Total `.py` files (non-`__init__`) | 178 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~79 (~44%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | ~160 (~90%) |
| Contain emoji | ~11 (~6%) |
| Subdirectories with README.md | 12 / 28 |
| Subdirectories with TEST_LOG.md | 1 / 28 |

### Key Problems

1. **Zero section banner compliance.** No file uses the `# ---------------------------------------------------------------------------` format. Some files use ad-hoc dividers like `# ************* Setup *************` but nothing standardized.

2. **Tracing database explosion.** `tracing/dbs/` has 14 near-identical files — the same HackerNews agent with `tracing=True`, differing only in the DB import line. This is the single biggest redundancy in the section.

3. **Database sync/async pairs.** `dbs/` has 3 duplicate pairs (`postgres_demo.py` / `async_postgres_demo.py`, `mongo_demo.py` / `async_mongo_demo.py`, `mysql_demo.py` / `async_mysql_demo.py`) that differ only in the DB class used.

4. **Poor documentation.** Only 12/28 directories have README.md. Only 1 directory (`scheduler/`) has TEST_LOG.md.

5. **Inconsistent naming.** Some files use `_demo` suffix (`postgres_demo.py`, `evals_demo.py`), others don't. No pattern.

6. **Emoji violations.** 11+ files contain emoji characters, concentrated in `workflow/`, `middleware/`, `tracing/`, and `advanced_demo/`.

7. **Root-level sprawl.** 14 files at root level mixing quickstart basics, schemas, demos, and feature examples. Needs reorganization into subdirectories (target: 3 at root).

### Overall Assessment

AgentOS has far less structural redundancy than agents/teams/workflows because:
- No systematic sync/async directory-level splits (like workflows)
- Each interface (Slack, WhatsApp, A2A, AGUI) is genuinely unique
- Each database backend is genuinely unique

The main restructuring work is: (1) eliminating the tracing/dbs explosion, (2) merging 3 sync/async DB pairs, (3) achieving 100% style compliance, and (4) adding comprehensive documentation.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 178 | ~161 |
| Style compliance | 0% | 100% |
| README coverage | 12/28 | All surviving directories |
| TEST_LOG coverage | 1/28 | All surviving directories |

---

## 2. Proposed Directory Structure

Reorganize root files into appropriate subdirectories. Keep only quickstart examples at root.

```
cookbook/05_agent_os/
├── basic.py                       # Minimal AgentOS setup
├── demo.py                        # Full-featured demo
├── agno_agent.py                  # Simple Claude-based agent
├── advanced_demo/                 # Multi-agent, knowledge, reasoning, MCP demos
├── background_tasks/              # Background hooks, evals, output evaluation
├── client/                        # AgentOSClient SDK usage (numbered 01-09 + server)
├── client_a2a/                    # A2A protocol client (numbered 01-05 + servers)
├── customize/                     # Custom FastAPI app, health, lifespan, routes, events, DI
├── dbs/                           # Database backend examples (15 backends + surreal_db/)
├── integrations/                  # [NEW] Third-party integrations (Shopify, etc.)
├── interfaces/
│   ├── a2a/                       # Agent-to-Agent protocol interface
│   │   └── multi_agent_a2a/       # Multi-agent A2A patterns
│   ├── agui/                      # AGUI interface
│   ├── slack/                     # Slack interface
│   └── whatsapp/                  # WhatsApp interface
├── knowledge/                     # Knowledge bases with AgentOS
├── mcp_demo/                      # Model Context Protocol integration
│   └── dynamic_headers/           # Dynamic header client/server
├── middleware/                     # JWT, custom middleware, content extraction, guardrails
├── os_config/                     # AgentOS configuration (basic, YAML)
├── rbac/                          # Role-based access control
│   ├── asymmetric/                # Asymmetric JWT
│   └── symmetric/                 # Symmetric JWT
├── remote/                        # Remote agents, teams, A2A, ADK gateway
├── scheduler/                     # Task scheduling
├── schemas/                       # [NEW] Agent and team input/output schemas
├── skills/                        # Skills integration
├── tracing/                       # OpenTelemetry tracing
│   └── dbs/                       # Tracing with different DB backends (3 representative)
└── workflow/                      # Workflow patterns with AgentOS
```

### Changes from Current

| Change | Details |
|--------|---------|
| **SLIM ROOT** from 14 to 3 files | Move schemas, events, DI, evals, guardrails, interfaces, shopify to subdirectories |
| **ADD** `schemas/` | New directory for agent/team input/output schema examples |
| **ADD** `integrations/` | New directory for third-party integrations (Shopify) |
| **EXPAND** `customize/` | Absorbs `handle_custom_events.py`, `pass_dependencies_to_agent.py`, `update_from_lifespan.py` from root |
| **EXPAND** `middleware/` | Absorbs `guardrails_demo.py` from root |
| **EXPAND** `background_tasks/` | Absorbs `evals_demo.py` from root |
| **MERGE** dbs/ sync/async pairs | 3 pairs → 3 files (postgres, mongo, mysql) |
| **CONSOLIDATE** tracing/dbs/ | 14 files → 3 representative examples. Full DB list in README |
| **MERGE** knowledge sync/async | `agentos_knowledge.py` + `agentos_knowledge_async.py` → 1 file |
| **MERGE** workflow stream pair | `workflow_with_custom_function.py` + `..._stream.py` → 1 file |
| **MERGE** root schema files | 4 schema files → 2 (`agent_schemas.py`, `team_schemas.py`) in `schemas/` |

---

## 3. File Disposition Table

### Root Level (14 files → 3 at root + 11 redistributed)

**Stay at root (3 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Minimal AgentOS setup. Add docstring, banners |
| `demo.py` | **KEEP + FIX** | Full-featured demo. Add banners |
| `agno_agent.py` | **KEEP + FIX** | Shows Claude model variant. Add docstring, banners |

**Move to `schemas/` (4 → 2 files, merged):**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `agent_with_input_schema.py` | **REWRITE** | `schemas/agent_schemas.py` | Merge input + output schema into one file |
| `agent_with_output_schema.py` | **MERGE INTO** `schemas/agent_schemas.py` | — | Output schema — same concept |
| `team_with_input_schema.py` | **REWRITE** | `schemas/team_schemas.py` | Merge team input + output schema into one file |
| `team_with_output_schema.py` | **MERGE INTO** `schemas/team_schemas.py` | — | Team output schema — same concept |

**Move to `customize/` (3 files):**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `handle_custom_events.py` | **KEEP + MOVE + FIX** | `customize/handle_custom_events.py` | Custom events are a customization pattern |
| `pass_dependencies_to_agent.py` | **KEEP + MOVE + FIX** | `customize/pass_dependencies_to_agent.py` | Dependency injection is a customization pattern |
| `update_from_lifespan.py` | **KEEP + MOVE + FIX** | `customize/update_from_lifespan.py` | Lifespan updates belong with customization |

**Move to existing directories (3 files):**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `all_interfaces.py` | **KEEP + MOVE + FIX** | `interfaces/all_interfaces.py` | Belongs with interface examples |
| `evals_demo.py` | **KEEP + MOVE + FIX** | `background_tasks/evals_demo.py` | Evals complement existing background_evals_example.py |
| `guardrails_demo.py` | **KEEP + MOVE + FIX** | `middleware/guardrails_demo.py` | Guardrails function as request middleware |

**Move to new `integrations/` (1 file):**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `shopify_demo.py` | **KEEP + MOVE + FIX** | `integrations/shopify_demo.py` | Third-party integration — own directory for future growth |

---

### `advanced_demo/` (9 → 9, no change)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `demo.py` | **KEEP + FIX** | `demo.py` | Full advanced demo. Add banners |
| `file_output.py` | **KEEP + FIX** | `file_output.py` | Unique: file output handling. Add banners |
| `mcp_demo.py` | **KEEP + FIX** | `mcp_demo.py` | Unique: MCP integration. Add banners |
| `multiple_knowledge_bases.py` | **KEEP + FIX** | `multiple_knowledge_bases.py` | Unique: multi-KB. Add banners |
| `reasoning_demo.py` | **KEEP + FIX** | `reasoning_demo.py` | Unique: reasoning patterns. Add banners |
| `reasoning_model.py` | **KEEP + FIX** | `reasoning_model.py` | Unique: reasoning model setup. Add banners |
| `teams_demo.py` | **KEEP + FIX** | `teams_demo.py` | Unique: team coordination. Add banners |
| `_agents.py` | **KEEP + FIX** | `_agents.py` | Helper file for demo.py. Add banners. Not directly runnable |
| `_teams.py` | **KEEP + FIX** | `_teams.py` | Helper file for demo.py. Add banners. Not directly runnable |

**Note:** `_agents.py` and `_teams.py` are helper modules imported by `demo.py`. They don't need a main gate but do need docstring and banners. Remove emoji from `_agents.py`.

---

### `background_tasks/` (6 → 7, absorbs evals_demo.py from root)

| File | Disposition | Rationale |
|------|------------|-----------|
| `background_evals_example.py` | **KEEP + FIX** | Unique: background evals. Add banners |
| `background_hooks_decorator.py` | **KEEP + FIX** | Unique: decorator-based hooks. Add banners |
| `background_hooks_example.py` | **KEEP + FIX** | Unique: basic background hooks. Add banners |
| `background_hooks_team.py` | **KEEP + FIX** | Unique: team-level hooks. Add banners |
| `background_hooks_workflow.py` | **KEEP + FIX** | Unique: workflow-level hooks. Add banners |
| `background_output_evaluation.py` | **KEEP + FIX** | Unique: output evaluation hooks. Add banners |
| `evals_demo.py` | **MOVED FROM ROOT** | Evaluation framework demo. Complements background_evals_example.py |

---

### `client/` (10 → 10, no change)

Well-organized numbered sequence with comprehensive README. All files are unique.

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_basic_client.py` | **KEEP + FIX** | Add banners |
| `02_run_agents.py` | **KEEP + FIX** | Add banners |
| `03_memory_operations.py` | **KEEP + FIX** | Add banners |
| `04_session_management.py` | **KEEP + FIX** | Add banners |
| `05_knowledge_search.py` | **KEEP + FIX** | Add banners |
| `06_run_teams.py` | **KEEP + FIX** | Add banners |
| `07_run_workflows.py` | **KEEP + FIX** | Add banners |
| `08_run_evals.py` | **KEEP + FIX** | Add banners |
| `09_upload_content.py` | **KEEP + FIX** | Add banners |
| `server.py` | **KEEP + FIX** | Reference server for client examples. Add banners |

---

### `client_a2a/` (7 → 7, no change)

Well-organized numbered sequence. All files unique.

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_basic_messaging.py` | **KEEP + FIX** | Add banners |
| `02_streaming.py` | **KEEP + FIX** | Add banners |
| `03_multi_turn.py` | **KEEP + FIX** | Add banners |
| `04_error_handling.py` | **KEEP + FIX** | Add banners |
| `05_connect_to_google_adk.py` | **KEEP + FIX** | Add banners |
| `servers/agno_server.py` | **KEEP + FIX** | Add banners |
| `servers/google_adk_server.py` | **KEEP + FIX** | Add banners |

---

### `customize/` (4 → 7, absorbs 3 files from root)

| File | Disposition | Rationale |
|------|------------|-----------|
| `custom_fastapi_app.py` | **KEEP + FIX** | Unique: custom FastAPI app. Add banners |
| `custom_health_endpoint.py` | **KEEP + FIX** | Unique: health endpoint. Add banners |
| `custom_lifespan.py` | **KEEP + FIX** | Unique: custom lifespan. Add banners |
| `override_routes.py` | **KEEP + FIX** | Unique: route overriding. Add banners |
| `handle_custom_events.py` | **MOVED FROM ROOT** | Custom event handling is a customization pattern |
| `pass_dependencies_to_agent.py` | **MOVED FROM ROOT** | Dependency injection is a customization pattern |
| `update_from_lifespan.py` | **MOVED FROM ROOT** | Lifespan update pattern belongs here |

---

### `dbs/` (22 → 19)

**Sync/async merges (3 pairs → 3 files):**

| File(s) | Disposition | New Name | Rationale |
|---------|------------|----------|-----------|
| `postgres_demo.py` + `async_postgres_demo.py` | **REWRITE** | `postgres.py` | Merge sync `PostgresDb` + async `AsyncPostgresDb` into one file. Show both patterns |
| `mongo_demo.py` + `async_mongo_demo.py` | **REWRITE** | `mongo.py` | Merge sync + async Mongo variants |
| `mysql_demo.py` + `async_mysql_demo.py` | **REWRITE** | `mysql.py` | Merge sync + async MySQL variants |

**Single-backend files (rename to drop `_demo` suffix):**

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `agentos_default_db.py` | **KEEP + FIX** | `agentos_default_db.py` | Unique: default DB behavior. Add banners |
| `dynamo_demo.py` | **KEEP + RENAME + FIX** | `dynamo.py` | Drop `_demo`. Add banners |
| `firestore_demo.py` | **KEEP + RENAME + FIX** | `firestore.py` | Drop `_demo`. Add banners |
| `gcs_json_demo.py` | **KEEP + RENAME + FIX** | `gcs_json.py` | Drop `_demo`. Add banners |
| `json_demo.py` | **KEEP + RENAME + FIX** | `json_db.py` | Drop `_demo`. Rename to avoid stdlib collision. Add banners |
| `neon_demo.py` | **KEEP + RENAME + FIX** | `neon.py` | Drop `_demo`. Add banners |
| `redis_demo.py` | **KEEP + RENAME + FIX** | `redis_db.py` | Drop `_demo`. Rename to avoid stdlib collision. Add banners |
| `singlestore_demo.py` | **KEEP + RENAME + FIX** | `singlestore.py` | Drop `_demo`. Add banners |
| `sqlite_demo.py` | **KEEP + RENAME + FIX** | `sqlite.py` | Drop `_demo`. Add banners |
| `supabase_demo.py` | **KEEP + RENAME + FIX** | `supabase.py` | Drop `_demo`. Add banners |
| `surreal_demo.py` | **KEEP + RENAME + FIX** | `surreal.py` | Drop `_demo`. Add banners |

**`surreal_db/` subdirectory (5 files, no change):**

Multi-file setup where `run.py` imports from sibling modules. Keep as-is. Apply style fixes.

| File | Disposition | Rationale |
|------|------------|-----------|
| `agents.py` | **KEEP + FIX** | Helper module. Add banners. Not directly runnable |
| `db.py` | **KEEP + FIX** | Database config helper. Add banners. Not directly runnable |
| `run.py` | **KEEP + FIX** | Main entry point. Add banners |
| `teams.py` | **KEEP + FIX** | Helper module. Add banners. Not directly runnable |
| `workflows.py` | **KEEP + FIX** | Helper module. Add banners. Not directly runnable |

---

### `integrations/` (NEW — 1 file from root)

| File | Disposition | Rationale |
|------|------------|-----------|
| `shopify_demo.py` | **MOVED FROM ROOT** | Third-party integration. New directory for future integrations |

---

### `interfaces/` (31 → 32, absorbs all_interfaces.py from root)

Each interface is genuinely unique — different integration classes, different capabilities. No merges.

**Root-level interface file:**

| File | Disposition | Rationale |
|------|------------|-----------|
| `all_interfaces.py` | **MOVED FROM ROOT** | Shows all interface types in one app. Add banners |

**`a2a/` (8 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add docstring, banners |
| `agent_with_tools.py` | **KEEP + FIX** | Unique: tools over A2A. Add banners |
| `reasoning_agent.py` | **KEEP + FIX** | Unique: reasoning over A2A. Add banners |
| `research_team.py` | **KEEP + FIX** | Unique: team over A2A. Add banners |
| `structured_output.py` | **KEEP + FIX** | Unique: schemas over A2A. Add banners |
| `multi_agent_a2a/airbnb_agent.py` | **KEEP + FIX** | Part of multi-agent example. Add banners |
| `multi_agent_a2a/trip_planning_a2a_client.py` | **KEEP + FIX** | Client for multi-agent demo. Add banners |
| `multi_agent_a2a/weather_agent.py` | **KEEP + FIX** | Part of multi-agent example. Add banners |

**`agui/` (7 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add banners |
| `agent_with_silent_tools.py` | **KEEP + FIX** | Unique: silent tools. Add banners |
| `agent_with_tools.py` | **KEEP + FIX** | Add banners |
| `multiple_instances.py` | **KEEP + FIX** | Unique: multi-instance. Add banners |
| `reasoning_agent.py` | **KEEP + FIX** | Add banners |
| `research_team.py` | **KEEP + FIX** | Add banners |
| `structured_output.py` | **KEEP + FIX** | Add banners |

**`slack/` (9 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add banners |
| `agent_with_user_memory.py` | **KEEP + FIX** | Unique: user memory via Slack. Add banners |
| `basic_workflow.py` | **KEEP + FIX** | Unique: workflow via Slack. Add banners |
| `channel_summarizer.py` | **KEEP + FIX** | Unique: channel summarization. Add banners |
| `file_analyst.py` | **KEEP + FIX** | Unique: file analysis via Slack. Add banners |
| `multiple_instances.py` | **KEEP + FIX** | Unique: multi-instance. Add banners |
| `reasoning_agent.py` | **KEEP + FIX** | Add banners |
| `research_assistant.py` | **KEEP + FIX** | Add banners |
| `support_team.py` | **KEEP + FIX** | Unique: support team via Slack. Add banners |

**`whatsapp/` (7 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add banners |
| `agent_with_media.py` | **KEEP + FIX** | Unique: media handling. Add banners |
| `agent_with_user_memory.py` | **KEEP + FIX** | Unique: user memory via WhatsApp. Add banners |
| `image_generation_model.py` | **KEEP + FIX** | Unique: image gen via model. Add banners |
| `image_generation_tools.py` | **KEEP + FIX** | Unique: image gen via tools. Add banners |
| `multiple_instances.py` | **KEEP + FIX** | Add banners |
| `reasoning_agent.py` | **KEEP + FIX** | Add banners |

---

### `knowledge/` (4 → 3)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `agentos_knowledge.py` | **REWRITE** | `agentos_knowledge.py` | Merge sync + async patterns into one file |
| `agentos_knowledge_async.py` | **MERGE INTO** `agentos_knowledge.py` | — | Async variant — same concept |
| `agentos_excel_analyst.py` | **KEEP + FIX** | `agentos_excel_analyst.py` | Unique: Excel knowledge base. Add banners |
| `agno_docs_agent.py` | **KEEP + FIX** | `agno_docs_agent.py` | Unique: docs knowledge agent. Add banners |

---

### `mcp_demo/` (7 → 7, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `enable_mcp_example.py` | **KEEP + FIX** | Unique: basic MCP enabling. Add banners |
| `mcp_tools_advanced_example.py` | **KEEP + FIX** | Unique: advanced MCP. Add banners |
| `mcp_tools_example.py` | **KEEP + FIX** | Unique: MCP tools. Add banners |
| `mcp_tools_existing_lifespan.py` | **KEEP + FIX** | Unique: MCP with lifespan. Add banners |
| `test_client.py` | **KEEP + FIX** | Unique: MCP test client. Add banners |
| `dynamic_headers/client.py` | **KEEP + FIX** | Dynamic headers client. Add banners |
| `dynamic_headers/server.py` | **KEEP + FIX** | Dynamic headers server. Add banners |

---

### `middleware/` (5 → 6, absorbs guardrails_demo.py from root)

| File | Disposition | Rationale |
|------|------------|-----------|
| `agent_os_with_custom_middleware.py` | **KEEP + FIX** | Unique: custom middleware. Add banners. Remove emoji |
| `agent_os_with_jwt_middleware.py` | **KEEP + FIX** | Unique: JWT middleware. Add banners |
| `agent_os_with_jwt_middleware_cookies.py` | **KEEP + FIX** | Unique: JWT + cookies. Add banners |
| `custom_fastapi_app_with_jwt_middleware.py` | **KEEP + FIX** | Unique: custom app + JWT. Add banners |
| `extract_content_middleware.py` | **KEEP + FIX** | Unique: content extraction. Add banners. Remove emoji |
| `guardrails_demo.py` | **MOVED FROM ROOT** | Guardrails function as request-level validation. Add banners |

---

### `os_config/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add banners |
| `yaml_config.py` | **KEEP + FIX** | Unique: YAML configuration. Add banners |

---

### `rbac/` (7 → 7, no change)

Good organization with comprehensive README. All files unique.

**`asymmetric/` (2 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add banners |
| `custom_scope_mappings.py` | **KEEP + FIX** | Unique: custom scope mappings. Add banners |

**`symmetric/` (5 files):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic.py` | **KEEP + FIX** | Add banners |
| `advanced_scopes.py` | **KEEP + FIX** | Unique: advanced scopes. Add banners |
| `agent_permissions.py` | **KEEP + FIX** | Unique: per-agent permissions. Add banners |
| `custom_scope_mappings.py` | **KEEP + FIX** | Add banners |
| `with_cookie.py` | **KEEP + FIX** | Unique: cookie-based auth. Add banners |

---

### `remote/` (8 → 8, no change)

Good numbering and README. All files unique.

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_remote_agent.py` | **KEEP + FIX** | Add banners |
| `02_remote_team.py` | **KEEP + FIX** | Add banners |
| `03_remote_agno_a2a_agent.py` | **KEEP + FIX** | Add banners |
| `04_remote_adk_agent.py` | **KEEP + FIX** | Add banners |
| `05_agent_os_gateway.py` | **KEEP + FIX** | Add banners |
| `server.py` | **KEEP + FIX** | Reference server. Add banners |
| `agno_a2a_server.py` | **KEEP + FIX** | A2A server. Add banners |
| `adk_server.py` | **KEEP + FIX** | ADK server. Add banners |

---

### `schemas/` (NEW — 2 files merged from 4 root files)

| File | Disposition | Rationale |
|------|------------|-----------|
| `agent_schemas.py` | **REWRITE** | Merge `agent_with_input_schema.py` + `agent_with_output_schema.py` from root. Show both patterns |
| `team_schemas.py` | **REWRITE** | Merge `team_with_input_schema.py` + `team_with_output_schema.py` from root. Show both patterns |

---

### `scheduler/` (2 → 2, no change)

Best-documented directory — has README, TEST_LOG, and CLAUDE.md.

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic_schedule.py` | **KEEP + FIX** | Add banners |
| `schedule_management.py` | **KEEP + FIX** | Add banners |

---

### `skills/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `skills_with_agentos.py` | **KEEP + FIX** | Add banners |
| `sample_skills/system-info/scripts/get_system_info.py` | **KEEP** | Helper script, not a cookbook example |
| `sample_skills/system-info/scripts/list_directory.py` | **KEEP** | Helper script, not a cookbook example |

---

### `tracing/` (21 → 10)

**Main tracing files (7, no change):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_basic_agent_tracing.py` | **KEEP + FIX** | Add banners |
| `02_basic_team_tracing.py` | **KEEP + FIX** | Add banners |
| `03_agent_with_knowledge_tracing.py` | **KEEP + FIX** | Add banners |
| `04_agent_with_reasoning_tools_tracing.py` | **KEEP + FIX** | Remove emoji. Add banners |
| `05_basic_workflow_tracing.py` | **KEEP + FIX** | Add banners |
| `06_tracing_with_multi_db_scenario.py` | **KEEP + FIX** | Add banners |
| `07_tracing_with_multi_db_and_tracing_flag.py` | **KEEP + FIX** | Add banners |

**`tracing/dbs/` (14 → 3):**

The 14 files are nearly identical — same HackerNews agent with `tracing=True`, differing only in the DB import. Keep 3 representative examples covering different DB categories. Document the full list of supported backends in README.

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic_agent_with_postgresdb.py` | **KEEP + FIX** | Representative: PostgreSQL (production DB). Add banners |
| `basic_agent_with_sqlite.py` | **KEEP + FIX** | Representative: SQLite (local dev). Add banners |
| `basic_agent_with_mongodb.py` | **KEEP + FIX** | Representative: MongoDB (document DB). Add banners |
| `basic_agent_with_async_mysql.py` | **CUT** | Redundant: async MySQL variant |
| `basic_agent_with_async_postgres.py` | **CUT** | Redundant: covered by main tracing examples |
| `basic_agent_with_async_sqlite.py` | **CUT** | Redundant: async SQLite variant |
| `basic_agent_with_dynamodb.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_firestore.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_gcs_json_db.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_jsondb.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_mysql.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_redis.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_singlestore.py` | **CUT** | Redundant: same pattern, different import |
| `basic_agent_with_surrealdb.py` | **CUT** | Redundant: same pattern, different import |

---

### `workflow/` (16 → 15)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `basic_workflow.py` | **KEEP + FIX** | `basic_workflow.py` | Add banners |
| `basic_workflow_team.py` | **KEEP + FIX** | `basic_workflow_team.py` | Add banners |
| `basic_chat_workflow_agent.py` | **KEEP + FIX** | `basic_chat_workflow_agent.py` | Add banners |
| `customer_research_workflow_parallel.py` | **KEEP + FIX** | `customer_research_workflow_parallel.py` | Remove emoji. Add banners |
| `workflow_with_conditional.py` | **KEEP + FIX** | `workflow_with_conditional.py` | Add banners |
| `workflow_with_custom_function.py` | **REWRITE** | `workflow_with_custom_function.py` | Merge sync + stream variants. Remove emoji. Add banners |
| `workflow_with_custom_function_stream.py` | **MERGE INTO** above | — | Stream variant of custom function — merge as async streaming section |
| `workflow_with_custom_function_updating_session_state.py` | **KEEP + FIX** | `workflow_with_custom_function_updating_session_state.py` | Remove emoji. Add banners |
| `workflow_with_history.py` | **KEEP + FIX** | `workflow_with_history.py` | Remove emoji. Add banners |
| `workflow_with_input_schema.py` | **KEEP + FIX** | `workflow_with_input_schema.py` | Add banners |
| `workflow_with_loop.py` | **KEEP + FIX** | `workflow_with_loop.py` | Remove emoji. Add banners |
| `workflow_with_nested_steps.py` | **KEEP + FIX** | `workflow_with_nested_steps.py` | Add banners |
| `workflow_with_parallel.py` | **KEEP + FIX** | `workflow_with_parallel.py` | Add banners |
| `workflow_with_parallel_and_custom_function_step_stream.py` | **KEEP + FIX** | `workflow_with_parallel_and_custom_function_step_stream.py` | Different feature from plain parallel. Add banners |
| `workflow_with_router.py` | **KEEP + FIX** | `workflow_with_router.py` | Add banners |
| `workflow_with_steps.py` | **KEEP + FIX** | `workflow_with_steps.py` | Add banners |

---

## 4. New Files Needed

AgentOS already has good feature coverage. No critical gaps requiring new files. Focus should be on style compliance and documentation.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `05_agent_os/` (root) | EXISTS | **MISSING** |
| `advanced_demo/` | **MISSING** | **MISSING** |
| `background_tasks/` | EXISTS | **MISSING** |
| `client/` | EXISTS | **MISSING** |
| `client_a2a/` | EXISTS | **MISSING** |
| `customize/` | **MISSING** | **MISSING** |
| `dbs/` | **MISSING** | **MISSING** |
| `integrations/` | **NEW DIR** | **NEW DIR** |
| `interfaces/` | **MISSING** | **MISSING** |
| `interfaces/a2a/` | EXISTS | **MISSING** |
| `interfaces/a2a/multi_agent_a2a/` | EXISTS | **MISSING** |
| `interfaces/agui/` | EXISTS | **MISSING** |
| `interfaces/slack/` | EXISTS | **MISSING** |
| `interfaces/whatsapp/` | **MISSING** | **MISSING** |
| `knowledge/` | **MISSING** | **MISSING** |
| `mcp_demo/` | **MISSING** | **MISSING** |
| `middleware/` | **MISSING** | **MISSING** |
| `os_config/` | **MISSING** | **MISSING** |
| `rbac/` | EXISTS | **MISSING** |
| `remote/` | EXISTS | **MISSING** |
| `scheduler/` | EXISTS | EXISTS |
| `schemas/` | **NEW DIR** | **NEW DIR** |
| `skills/` | EXISTS | **MISSING** |
| `tracing/` | **MISSING** | **MISSING** |
| `workflow/` | **MISSING** | **MISSING** |

**Summary:** 12/25 directories have README.md. 1/25 has TEST_LOG.md. After restructuring, every directory with runnable `.py` files needs both.

---

## 6. Recommended Cookbook Template

AgentOS files are **server apps**, not standalone scripts. The key difference from agents/teams/workflows:
- `app = agent_os.get_app()` MUST be at module level (uvicorn imports it)
- The main gate contains `agent_os.serve(...)` instead of `agent.print_response(...)`

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using AgentOS.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Example Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description="Example AgentOS app",
    agents=[agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB, config) → Create Agents/Teams/Workflows → Create AgentOS → Run
5. **`app` at module level** — `app = agent_os.get_app()` MUST be in the "Create AgentOS" section, not inside the main gate. Uvicorn imports it.
6. **Main gate** — Contains `agent_os.serve(app="module:app", ...)`. The `app` string must match the filename.
7. **No emoji** — No emoji characters anywhere
8. **Self-contained** — Each file must be independently runnable via `.venvs/demo/bin/python <path>`

### Best Current Examples (reference)

1. **`basic.py`** — Good minimal structure. Has docstring and main gate. Needs: section banners.
2. **`client/01_basic_client.py`** — Good docstring, numbered sequence, comprehensive. Needs: banners.
3. **`scheduler/basic_schedule.py`** — Good docstring, main gate. Only directory with TEST_LOG. Needs: banners.
