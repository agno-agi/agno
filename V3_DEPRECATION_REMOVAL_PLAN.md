# v3.0 Deprecation Audit and Removal Plan

## Execution status (2026-08-14)

Tiers 0-3 are REMOVED on this branch (see the tiered commits in this PR), with two
deviations, both conservative:

- **SSE standalone transport (3.4): kept, warning upgraded.** SSE is live functionality
  (SSE-only servers exist; the Pipedream/mem0 cookbooks point at SSE endpoints), and the
  only prior signal was a `log_info`. This branch upgrades it to a `log_warning` naming the
  removal; full removal should be its own PR after the cookbooks are re-verified against
  streamable-http endpoints.
- **LanceDB `table_names` fallback: kept.** Could not verify `list_tables` exists at the
  pinned `lancedb>=0.26.0` floor in this environment; the `hasattr` fallback is cheap and
  safe. Drop it once verified.
- **Seltz legacy SDK path: kept.** Removing it requires a `seltz` version-floor bump that
  could not be verified (current pin `seltz>=0.2.0`). Only the deprecated `max_documents`
  alias was removed.

Tier 4 (silent deprecations needing a warning cycle or product decision) and Tier 5
(data-migration-gated) remain as documented below - they are the follow-up work.

---

Exhaustive inventory of every deprecated, to-be-deprecated, and backward-compat item in
`libs/agno/agno` as of `feat/v3.0` (audited at commit `7206f7763`, 2026-08-14).
`libs/agno_infra` and `libs/agnoctl` were swept and contain no deprecation markers.

Each item lists: location, replacement, warning mechanism today, what removal entails, and
known breakage in `libs/`, `cookbook/`, and `libs/agno/tests/`.

**Headline numbers**

- 60+ distinct items found. Only a handful emit a real `DeprecationWarning`; most are
  docstring-only or fully silent, so users have had no programmatic migration signal.
- Exactly one item is explicitly promised for removal in 3.0: `LearningMode.HITL`.
- One item is overdue by a full major version: the Qdrant unnamed-vector compat layer is
  tagged `TODO(v2.0.0)`.
- Three latent bugs were found during the audit (see "Bugs found" at the end).

**Already done on `feat/v3.0`** (no action needed, listed to avoid re-litigating):

- Agent/Team constructor params `search_session_history`, `num_history_sessions`,
  `enable_user_memories`, `num_past_session_runs` are fully renamed
  (`search_past_sessions`, `num_past_sessions_to_search`, `update_memory_on_run`,
  `num_past_session_runs_in_search`). Only `from_dict` drop-shims remain (Tier 1).
- `AuthMiddleware.__init__` no longer accepts `secret_key`. Two dead references remain
  (Tier 1).
- The `deprecated=True` FastAPI fields that existed on main in
  `os/routers/{agents,teams}/schema.py` are already gone.

---

## Tier 0 - Promised for 3.0, remove now

### 0.1 `LearningMode.HITL`

- **Where:** `libs/agno/agno/learn/config.py:48` (enum member), docstrings at lines 10 and
  42 ("HITL: Deprecated, unsupported by every store; removed in 3.0.").
- **Replacement:** `LearningMode.PROPOSE`.
- **Warning today:** per-store `log_warning` at construction
  (`learn/stores/user_profile.py:91`, `user_memory.py:81`, `learned_knowledge.py:81`),
  deliberately not worded as a deprecation.
- **Removal:** delete the enum member, the three store guard branches, and drop `HITL` from
  `modes_needing_history` in `learn/machine.py:432`. Persisted configs with `mode: "hitl"`
  degrade gracefully via the invalid-mode salvage path at `learn/machine.py:1145-1160`.
- **Breakage:** `tests/unit/learn/test_deprecations_and_guards.py:46-56`
  (`test_hitl_mode_warns_unsupported_without_deprecating`) pins current behavior and must be
  replaced with a "hitl mode is rejected/salvaged" test.

---

## Tier 1 - Clean deletes, zero or near-zero external usage

### Modules

| Item | Where | Replacement | Notes |
|---|---|---|---|
| `agno.tools.gmail` stub | `tools/gmail.py` (whole file) | `agno.tools.google.gmail` | `DeprecationWarning` at import. Zero usages; tests already on new path. |
| `agno.tools.googlesheets` stub | `tools/googlesheets.py` | `agno.tools.google.sheets` | Same. |
| `agno.tools.googlecalendar` stub | `tools/googlecalendar.py` | `agno.tools.google.calendar` | Same. |
| `agno.tools.google_maps` stub | `tools/google_maps.py` | `agno.tools.google.maps` | Same. |
| `agno.tools.google_drive` stub | `tools/google_drive.py` | `agno.tools.google.drive` | Same. |
| `agno.tools.google_bigquery` stub | `tools/google_bigquery.py` | `agno.tools.google.bigquery` | Also re-exports private `_clean_sql`. Same. |

### Params and methods

| Item | Where | Replacement | Warning | Breakage |
|---|---|---|---|---|
| `enable_list_tables`, `enable_describe_table`, `enable_run_sql_query` | `tools/google/bigquery.py:33-36,50-53` | `list_tables`, `describe_table`, `run_sql_query` | Silent (comment only) | None. Caution: `tools/sql.py` has identically named params that are canonical there; no blind grep-replace. |
| `use_tantivy` | `vectordb/lancedb/lance_db.py:42,64,165-166` | None (param is ignored; native FTS is unconditional) | `log_warning` when truthy | None; zero external usages. |
| `SurrealDb._table_exists` | `db/surrealdb/surrealdb.py:172-174` | `table_exists()` | Docstring only | Update internal caller at `surrealdb.py:213`. |
| `PgVector.enable_prefix_matching` | `vectordb/pgvector/pgvector.py:926-945` | `_build_ts_query` | Docstring only; output silently discarded on default code path | Delete `tests/unit/vectordb/test_pgvector.py:1161-1169` with it. |
| LanceDB `table_names` fallback | `vectordb/lancedb/lance_db.py:175-187` | `conn.list_tables()` unconditionally | Silent | Verify `list_tables` exists at pinned `lancedb>=0.26.0` (pyproject:182); if yes this is dead code. |
| `output_path` dead param | `tools/brightdata.py:125,131` | None (accepted and ignored) | Docstring only | None. |
| `Knowledge.add_content`, `add_content_async`, `add_contents_async` | `knowledge/knowledge.py:3428-3583` (file tail; clean truncation) | `insert()`, `ainsert()`, `ainsert_many()` | Docstring only ("will be removed in a future version"); silent at runtime | 4 archived cookbooks (`cookbook/07_knowledge/09_archive/vector_dbs/{opensearch_db,opensearch_db_hybrid_search,async_opensearch_db,async_opensearch_db_with_batch_embedder}.py`) and one checklist line in `cookbook/07_knowledge/TEST_PROMPT.md:51`. No tests call them. |

### Aliases and shims

| Item | Where | Replacement | Breakage |
|---|---|---|---|
| `MemoriesConfig = UserMemoryConfig` | `learn/config.py:183` + exports in `learn/__init__.py:18,50` | `UserMemoryConfig` | None; zero usages. |
| `MemoriesStore = UserMemoryStore` | `learn/stores/user_memory.py:1528` + exports in `learn/stores/__init__.py:26,33` and `learn/__init__.py:37,66` | `UserMemoryStore` | None; zero usages. |
| `Decision = DecisionLog` | `learn/schemas.py:1161-1162` | `DecisionLog` | None; not exported, zero usages. |
| Agent `from_dict` key-drop shims | `agent/_storage.py:1133-1147` | New key names already read via `config.get` | None; the pops are defensive, zero producers of old keys exist. |
| Team `from_dict` key-drop shims | `team/_storage.py:1229-1243` | Same | None. |
| `LEGACY_HITL_KEYS` + `drop_legacy_hitl_keys` | `workflow/utils/hitl.py:22-57`; call sites `step.py:611`, `condition.py:277`, `router.py:320`, `loop.py:274`, `steps.py:159` | `human_review=HumanReview(...)` | None; keys are already discarded, only the debug breadcrumb is lost. |
| Dead `secret_key` compat branches | `os/utils.py:1664-1670`, `os/middleware/jwt.py:391` | n/a - the param no longer exists on `AuthMiddleware.__init__`, so these branches are unreachable | None. Also fix the stale "Mirror JWTMiddleware.__init__ deprecated secret_key handling" comment. |
| Dead `enable_user_memories` write | `environments/runner.py:924` | n/a - attribute does not exist on Agent; write is a no-op | Must change together with the duck-typed stub in `tests/unit/environments/test_runner.py:107,139,204,264`, which is the only thing keeping the assertion green. See Bugs. |
| Stale legacy-flags comment | `tools/reasoning.py:37` | n/a | Comment only; the legacy flags are already gone. |

---

## Tier 2 - Deletes with mechanical rename churn (tests/cookbooks to update)

| Item | Where | Replacement | Breakage to fix |
|---|---|---|---|
| `Metrics = RunMetrics` alias | `metrics.py:443-444` | `RunMetrics` | 13 call sites in `tests/unit/test_model_type.py`, 1 in `tests/unit/response.py:11`. |
| `agno.models.metrics` re-export module | `models/metrics.py` (whole file) | `agno.metrics` | Agno's own core still imports through the shim: `agent/_run.py:47`, `agent/_tools.py:24`, `models/response.py:9`, `workflow/types.py:9`, plus ~17 model adapters and 9 test files. Migrate internal imports first (mechanical), then delete the shim. |
| `Model.classify_error` | `models/base.py:195-201` | `ModelProviderError.classify(error)` | Internal caller `models/base.py:245`; 5 call sites in `tests/unit/test_fallback.py`. |
| `RedisVectorDb = RedisDB` alias | `vectordb/redis/__init__.py:3-4,7` | `RedisDB` | `tests/unit/vectordb/test_redisdb.py:104-125` imports the alias; archived cookbook `redis_db.py:16,25`. |
| `StudioTool = StudioTools` alias | `tools/studio.py:2856-2858` | `StudioTools` | `tests/unit/tools/test_studio.py` (10 call sites). |
| `duckduckgo_search` / `duckduckgo_news` method aliases | `tools/duckduckgo.py:54-56` | `web_search`, `search_news` | `tests/unit/tools/test_duckduckgo.py:115-116`. |
| Seltz `max_documents` | `tools/seltz.py:37,51,68,183,196` + `_resolve_max_results` | `max_results` | 13 lines in `tests/unit/tools/test_seltz.py` incl. dedicated alias tests. |
| Seltz legacy SDK path (`context`, `profile`, `_search_legacy_sdk`, capability sniff) | `tools/seltz.py:53-54,69-70,114-126,156-177,225-245` | Pin `seltz>=1.2.0`, current SDK path only | `tests/unit/tools/test_seltz.py:283,286`. |
| `creds_path`, `auth_port` | `tools/google/drive.py:268-310` | `credentials_path`, `oauth_port` | `tests/unit/tools/test_google_drive.py:34`. Keep the `oauth_port` default at lines 311-312. |
| `creds_path`, `enable_read_sheet`, `enable_create_sheet`, `enable_update_sheet`, `enable_create_duplicate_sheet` | `tools/google/sheets.py:84-136` | `credentials_path`, `read_sheet`, `create_sheet`, `update_sheet`, `create_duplicate_sheet` | `tests/unit/tools/test_googlesheets_tools.py:51-75` (5 call sites). The four `enable_*` flags are docstring-only, silent. |
| `GDriveContextProvider` alias | `context/gdrive/__init__.py:3-6` | `GoogleDriveContextProvider` | `cookbook/12_context/21_gdrive_office.py:36,42` + README/TEST_LOG mentions. |
| `FileTools.check_escape` | `tools/file.py:134-145` | `_check_path(relative_path, self.base_dir)` | 7 internal call sites in `file.py` (156, 184, 211, 235, 256, 280, 359) + `tests/unit/tools/test_filetools.py` and `tests/unit/utils/test_path_safety_consistency.py`. Do not touch `local_file_system.py`'s own distinct `check_escape`. |
| `fallback_allowed(expected_attempt=...)` dead param | `run/status_persist.py:109-111` | Drop the param (documented as unused) | Update callers passing it. |
| `AgentOS(enable_mcp_server=...)`, `AgentOS(mcp_config=...)` + `enable_mcp_server` property | `os/app.py:281-284,352-356,395-425,544-552` | `mcp_server` | `tests/unit/os/test_mcp_server.py`. These do emit `DeprecationWarning`, so removal is fair game for 3.0. |

---

## Tier 3 - Deprecation is announced; removal is the real breaking change

### 3.1 Injected `session_state` parameter in workflow callables (cleanest "real" removal)

- **Where:** warner at `workflow/types.py:20-32`; call sites `step.py:893,911`,
  `condition.py:400,446`, `router.py:557,601`, each inside a signature-inspection branch
  that still injects `session_state` into user callables.
- **Replacement:** `run_context: RunContext` -> `run_context.session_state`.
- **Warning today:** `log_warning`, once per component/function name.
- **Removal:** delete the helper, module-level dedup set, 3 imports, 6 call sites, and the
  injection branches. Step functions declaring `session_state` then fail with a missing-arg
  error instead of a warning.
- **Breakage:** none in-repo - `cookbook/04_workflows/` is fully migrated. CEL
  `session_state.*` expressions are a separate live feature; do not touch.

### 3.2 `MultiMCPTools` (largest blast radius in the audit)

- **Where:** `tools/mcp/multi_mcp.py` (class, `DeprecationWarning` in `__init__` at 82-86);
  export in `tools/mcp/__init__.py:2,7`.
- **Replacement:** multiple `MCPTools` instances.
- **Removal:** also remove ~30 `"MultiMCPTools"` name-check branches across core:
  `environments/runner.py:664`; `agent/_init.py`, `_tools.py`, `_cli.py`, `_utils.py`;
  `team/_init.py`, `_tools.py`, `_cli.py`, `_utils.py`; `os/utils.py` (10 sites),
  `os/app.py:804,807`; and a real `isinstance` branch in `utils/mcp.py:233`.
- **Breakage:** 5 cookbook files under `cookbook/91_tools/mcp/`, 5 test files
  (`tests/unit/tools/test_mcp.py`, `tests/unit/os/test_per_request_isolation.py`,
  `test_registry_mcp_tools.py`, and 2 integration twins).

### 3.3 A2A dynamic-dispatch endpoints

- **Where:** `os/interfaces/a2a/router.py:896-1060`: `POST {prefix}/message/send` and
  `POST {prefix}/message/stream`, marked `[DEPRECATED]` in OpenAPI and emitting
  `DeprecationWarning` per request. Supporting pieces: `_enforce_dynamic_dispatch_scope`
  helper (`router.py:40-58`) and the scope map entries in
  `os/interfaces/a2a/scopes.py:21-22`.
- **Replacement:** entity-scoped `/agents/{id}/v1/message:send|stream` (and teams/workflows
  variants).
- **Removal:** delete both routes + helper + scope entries.
- **Breakage:** integration tests post to the dispatch routes
  (`tests/integration/os/interfaces/test_a2a.py`, `test_a2a_authorization.py`,
  `tests/system/tests/test_a2a_routes.py`). Note `client/a2a/client.py:173` uses
  `"message/send"` as the JSON-RPC method name per A2A protocol spec - that is not the
  deprecated URL and must stay.

### 3.4 SSE as a standalone MCP transport

- **Where:** `tools/mcp/mcp.py:105-106` (and `multi_mcp.py:90-92`, moot if 3.2 lands).
- **Replacement:** `transport="streamable-http"` (already the default when `url` is set).
- **Warning today:** `log_info` only - easy to miss. If not removing in 3.0, at minimum
  upgrade to `log_warning`.
- **Removal:** reject `"sse"` in the transport literal, delete the SSE client path and
  `SSEClientParams` (`tools/mcp/params.py`, re-exported in `tools/mcp/__init__.py:3,9`).
- **Breakage:** 5 cookbook files (`cookbook/91_tools/mcp/sse_transport/{client,server}.py`,
  `pipedream_slack.py`, `pipedream_linkedin.py`, `mem0.py`).

---

## Tier 4 - Silent today; either remove loudly in 3.0 or add a warning now and remove in 3.1

v3.0 is the natural break point; each of these needs an explicit decision because users
were never warned.

| Item | Where | Replacement | Recommendation |
|---|---|---|---|
| `websocket` implies `enable_websocket=True` | `workflow/workflow.py:8369-8371,10189-10191` | Pass `enable_websocket=True` explicitly | Removal causes a silent behavior regression (falls back to SSE queue). `cookbook/04_workflows/06_advanced_concepts/background_execution/websocket_server.py:221` depends on it. Either keep the coercion (it is arguably good UX) or raise on `websocket=` without `enable_websocket`. |
| `knowledge_retriever(dependencies=...)` signature support | `agent/_messages.py:1852-1855,1938-1941`; `team/_default_tools.py:1688-1692,1775-1779` | `knowledge_retriever(run_context: RunContext, ...)` | Silent `elif` branch; nobody was told to migrate. Add a once-per-function `log_warning` in 3.0, remove in 3.1. |
| mistralai v1 SDK support | `utils/models/_mistral_compat.py:45-60` | `mistralai>=2.0.0` | The "will be deprecated" notice is `log_debug` (invisible). Promote to `log_warning` in 3.0, or drop v1 + bump the packaging floor now. Sibling `_genai_compat.py` has the same dual-version pattern with no notice - decide together. |
| Google legacy auth params `service_account_path`, `delegated_user`, `oauth_port`, `login_hint` | `tools/google/base.py:27-45`; same shape in `context/calendar/provider.py:79-84`, `context/gmail/provider.py:87-92` | `auth=AuthConfig(...)` | Broad blast radius (every Google toolkit passes them through). Mixing with `auth=` already raises. Suggest keeping in 3.0 with a deprecation warning; remove in 3.1. |
| `header_provider` positional `run_context` support | `tools/mcp/mcp.py:267-269` (dup in `multi_mcp.py:253-255`) | Named `run_context` param | Silent fallthrough. Add warning or remove with release note. |
| `StepOutputEvent` proxy properties (`content`, `images`, `videos`, `audio`, `success`, `error`, `stop`) | `run/workflow.py:571-599` | `event.step_output.<field>` | `content` is consumed by `utils/print_response/workflow.py:722,1567` and likely by UI event streams; audit consumers before removing. |
| `BaseAgentRunEvent.content` / `BaseTeamRunEvent.content` | `run/agent.py:216-217`, `run/team.py:208-209` | Typed `content` on concrete events | Real dataclass fields, so they are in every event's `to_dict()` wire shape. Removing changes the wire format - coordinate with AgentOS UI. |
| AGUI `BinaryInputContent` flat structure | `os/interfaces/agui/input.py:62-68` | Source-object media parts | Comment says "deprecated but still used" - confirm the AG-UI client no longer sends flat parts before removing. |
| Legacy scope aliases `system:read`/`system:write` | `os/scopes.py:31-35,147,159,191,193` (+ docs at 20-21, 48-49, 425, 525) | `config:read`/`config:write` | Alias exists to keep issued tokens working. Removing invalidates outstanding tokens; decide based on token lifetimes. Tests use the legacy names (`tests/unit/os/test_scopes.py`, `tests/integration/os/test_authorization.py`). |
| `JWTMiddleware = AuthMiddleware` alias | `os/middleware/jwt.py:1212-1214` | `AuthMiddleware` | Pervasive: 13+ test files and security cookbooks use `JWTMiddleware`, and manual `add_middleware(JWTMiddleware, ...)` is documented public API. Keep the alias through 3.x; removing it buys nothing now. |
| `Searxng` vs `SearxngTools` | `tools/searxng.py:154-155` | Naming decision | The alias is the *convention-consistent* name. Recommend the inverse of removal: rename the class to `SearxngTools` and drop/deprecate `Searxng`. Cookbook uses `SearxngTools`. |
| `action=None` matches any scope action | `os/scopes.py:358,386` | Explicit action | Documented "backwards compatible for list filtering"; internal behavior, low value to change. |

---

## Tier 5 - Requires data migration or old-client cutoff; explicitly defer unless we commit to a migration

| Item | Where | Why deferred |
|---|---|---|
| Qdrant unnamed-vector compat (`use_named_vectors` + 5 conditionals + 2 create sites) | `vectordb/qdrant/qdrant.py:147-149,220-225,250-255,331-341,446-449,594-614,643-663` | Tagged `TODO(v2.0.0)` - overdue. But existing `SearchType.vector` collections have unnamed vectors and break on read after the switch. Needs a re-index/migration path and a loud release note. Biggest single cleanup available. Also contains a dead assignment (see Bugs). |
| Legacy `RunMetrics` -> `SessionMetrics` coercion (4 copies) | `agent/_storage.py:~372-392`, `team/_storage.py:~144-155`, `workflow/workflow.py:~10689`, plus the metrics module | Old session rows carry the legacy shape. Remove as one unit with a data migration, or keep. |
| `router_requirements` -> `step_requirements` from_dict shim | `run/workflow.py:1027-1039` | Old persisted paused runs lose their route-selection pause. Covered by `tests/unit/workflow/test_hitl.py:568`. |
| `from_dict` step-executor default to `RunOutput` | `run/workflow.py:981-982` | Old rows without discriminators would raise instead of degrading. |
| `normalize_tool_messages` (old combined Gemini tool messages) | `utils/message.py:50-85`; 12 call sites across all model adapters | Breaks replay of pre-migration Gemini sessions across every provider. Needs a message-table migration; not a cheap win. |
| Legacy `runs` column machinery (`cleanup_legacy_runs_column`/`_field`, 16 impls; `merge_runs_table_with_legacy_blob`) | `db/migrations/versions/v3_0_0.py`, `db/utils.py:331`, adapters | This is new v3.0 infrastructure, not debt. Out of scope; file the teardown as a v3.1+/v4 item. |
| v1 -> v2 migration module | `db/migrations/v1_to_v2.py` | Still wired into 4 adapters and documented. Keep. Improvement candidate: convert `get_all_table_content` (533-545) callers to the batched generator (OOM fix). |
| Content-hash backward-compat format | `knowledge/knowledge.py:2222` | Changing invalidates every existing content hash. Keep. |
| `isolate_vector_search=False` default | `knowledge/knowledge.py:53-57` | Default-flip candidate for 3.0 (not a deletion); flipping requires re-indexing for `linked_to` metadata. Decide as a product question. |
| Docling `allowed_hosts=None` (all hosts allowed) | `knowledge/reader/docling_reader.py:74-76` | Security-motivated default-flip candidate (SSRF surface). Decide alongside other 3.0 default changes. |
| Legacy `WorkflowRunOutput` SSE event for old clients | `os/routers/workflows/router.py:888-915,1060-1087` | Client-compat window question: safe to drop only when the UI fleet no longer needs it. |
| Legacy pause-shape fallback; legacy-data `ToolExecution` placeholder; `event_index=None` tolerance | `workflow/utils/hitl.py:543`; `run/requirement.py:257-259`; `run/base.py:56` | Defensive read paths over old rows. Keep. |
| `RunOutput`/`TeamRunOutput` union on `AgentSession.runs` "for legacy reasons" | `agent/_run.py:6388-6389,6437-6438` | Type-level cleanup: narrowing the union removes two casts. Low risk, but verify no team runs are ever stored in agent sessions before narrowing. |

**Behavioral fallbacks reviewed and recommended to KEEP as-is** (comments say "backward
compat" but they are product behavior, not deprecations): `output_directory` implying
`save_files`/`save_downloads` (`tools/file_generation.py:115`, `tools/slack.py:215`); Slack
primary-token-as-user-token fallback (`tools/slack.py:200-206`,
`context/slack/provider.py:73-78`); Slack `search_messages` legacy-API tool (off by
default); `os_security_key` auth paths (`os/auth.py:271`, `os/router.py:284-447` - live
feature); inline-blocking fallthrough for background runs
(`os/routers/{agents,teams}/router.py`); `user_isolation=False` default
(`os/routers/approvals/router.py`); `get_last_step_content()` (load-bearing, see below);
Valkey/Mongo vectordb aliases (`ValkeyVectorDb`, `MongoVectorDb` - intentional
disambiguation, not compat); SQLite `db_schema` ignored-param uniformity; `db_id` param on
`os/utils.get_db` (documented compat but harmless routing logic).

**Vendor/SDK notes (not agno API, no removal):** Claude prefill capability gate
(`utils/models/claude.py:12-63`) - upstream Anthropic deprecation, allow-list maintenance
only; `Engine.nmslib` (`vectordb/opensearch/index.py:13`) - keep for OpenSearch 2.x, default
is already `lucene`, add a `log_warning` on explicit selection; Pinecone `==5.4.2` pin +
v6 hard-block (`pineconedb.py:7-16`, pyproject:187) - a v3.0 release risk to resolve, not a
removal; Gemini `grounding`/`grounding_dynamic_threshold` (`models/google/gemini.py:341-343`,
`log_debug` points to `search`) - genuine deprecation candidate, add real warning; motor
driver: `pyproject.toml:166` `async-mongo` extra still installs `motor` while the code calls
it "legacy, deprecated" - drop it from the extra, keep the runtime support path.

---

## Bugs found during the audit (fix regardless of removals)

1. **Dead attribute write behind a false comment in a safety-critical block.**
   `environments/runner.py:924` sets `agent.enable_user_memories = False` with the comment
   "deprecated alias of update_memory_on_run". No such alias mechanism exists on v3.0
   Agent - the write creates a stray attribute nothing reads, and line 923
   (`update_memory_on_run = False`) is the only real barrier for post-run memory capture.
   The unit test only passes because its duck-typed stub defines the attribute
   (`tests/unit/environments/test_runner.py:107,139,204,264`). Delete line 924 and the stub
   fields together.
2. **Qdrant dead assignment.** In the sync insert path
   (`vectordb/qdrant/qdrant.py:331-341`), the `if self.use_named_vectors:` assignment is
   unconditionally overwritten by the following `SearchType.vector` branch - the two
   conditions are mutually exclusive, so the first assignment is dead on every path.
3. **Unreachable warnings.** `vectordb/pineconedb/pineconedb.py:11-16` and
   `knowledge/embedder/ollama.py:22-23` both `warnings.warn(...)` and then immediately
   `raise` - the warning can never be usefully observed. Also
   `db/mongo/async_mongo.py:82` is missing a trailing `\n`, so two install hints render on
   one line.

---

## Suggested execution order

1. **PR A (pure deletions, no user impact):** all of Tier 1 + Tier 0. Small, reviewable,
   unblocks everything else.
2. **PR B (rename churn):** Tier 2, mostly test/cookbook updates. Can be split by area
   (metrics/model, tools, vectordb, AgentOS).
3. **PR C (announced breaking removals):** Tier 3, one PR per item (session_state
   injection, MultiMCPTools, A2A dispatch routes, SSE transport), each with a migration
   note for the v3.0 changelog.
4. **PR D (warnings for the silent set):** add loud deprecation warnings for every Tier 4
   item we are keeping through 3.0, so they are legally removable in 3.1.
5. **Defer:** Tier 5 items stay, each tracked as its own issue with the required migration
   named.

Every removal PR should update the v3.0 migration guide; the audit's core finding is that
most of this surface was deprecated silently, so the migration guide is the only warning
most users will ever get.
