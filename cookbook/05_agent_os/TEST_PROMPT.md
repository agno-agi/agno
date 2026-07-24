# AgentOS Cookbook Test Prompt

Thoroughly test the complete AgentOS curriculum: root `basic.py` and numbered
lessons `01_getting_started` through `24_showcase`.

## Read first

- `AGENTS.md`
- `cookbook/STYLE_GUIDE.md`
- `cookbook/05_agent_os/README.md`
- Every Python file, README, and TEST_LOG in the root and lessons 01–24

Do not infer behavior from filenames or old test results. Verify parameters,
client methods, endpoints, form fields, and response shapes against
`libs/agno/agno` before changing an example.

## Environment

- Cookbook Python: `.venvs/demo/bin/python`
- Development checks: `.venv`
- Environment variables: load with `direnv allow` when available
- Postgres: `./cookbook/scripts/run_pgvector.sh`
- SurrealDB: `./cookbook/scripts/run_surrealdb.sh`

When using a development environment from a different checkout or worktree,
set `PYTHONPATH=<current-worktree>/libs/agno` so imports resolve to the source
being tested rather than another editable installation.

Use `tmp/` only for runtime artifacts. Remove generated databases,
`__pycache__`, and temporary server output when the run is complete.

## Result contract

Every Python file needs a dated entry in the nearest TEST_LOG with:

- `Status: PASS`
- `Test mode: LIVE` or `Test mode: CONSTRUCTION_SMOKE`
- The command or behavior tested
- Concrete observed output

`CONSTRUCTION_SMOKE` is reserved for credential-gated examples. It must prove
imports, object construction, app construction, and the expected registered
route. State which credentials were missing and what was not exercised.
Never leave a final FAIL, MANUAL, PENDING, unexecuted placeholder, or
fabricated success entry.

For each credentials-free server, boot it, assert `GET /health` returns 200,
inspect `GET /config`, and terminate it. For every client/server pair, run both
halves and record both observations.

## Lesson checks

### Root and 01_getting_started

- Root `basic.py`: verify `/health`, `/config`, the `agno-assist` agent, and
  MCP tool discovery.
- `full_os.py`: verify the agent, team, workflow, knowledge, sessions, and
  config surfaces are present.
- `run_over_http.py`: start `full_os.py`, then observe config discovery, a
  non-streaming run, SSE events, and the persisted session.

### 02_databases

- `basic.py`: verify the OS-level SQLite database is inherited by the agent
  and auto-provisioned.
- `postgres.py`: start pgvector and test both the sync and async database
  variants.
- `surreal.py`: start SurrealDB and observe a real persisted session.
- Confirm the README backend table uses real imports and constructor shapes,
  labels ClickHouse as traces-only, and documents `/databases/{id}/migrate`.

### 03_python_client

- Start `_server.py` on port 7778.
- Run clients 01–06 against it, including sync and async config, typed run
  streaming, session and memory CRUD, the complete knowledge lifecycle, eval
  result reads, and authenticated calls.
- Exercise both unauthenticated and `OS_SECURITY_KEY` modes where directed.

### 04_run_lifecycle

- Observe `background=true` plus `stream=false` return 202 with a database,
  then poll the nested run route with `session_id`.
- Start and cancel a long background run and observe its final status.
- Resume an interrupted SSE stream with the raw-httpx workaround.
- Use `checkpoint="tool-batch"`, list checkpoints, and continue from a
  selected `message_index`.
- Observe blocking and background hook/eval behavior.

### 05_human_in_the_loop

- Verify the README distinguishes ephemeral `requires_*` pauses from
  persistent `@approval` records.
- Run every pause-and-resume pair in the same file, including multi-round user
  input, external execution, team placement, and workflow review.
- List and resolve required approvals through `/approvals`; confirm an audit
  approval is paired with a real HITL flag.

### 06_customize

- Boot and inspect each base-app, route-conflict, lifespan, middleware,
  event, dependency, CORS, and security-key example.
- Confirm `base_app` is the real constructor parameter, middleware ordering is
  documented as LIFO, and response middleware uses no private Starlette type.
- Verify unauthenticated and authenticated behavior for `OS_SECURITY_KEY`.

### 07_security

- Run HS256 and RS256 examples and observe both allowed and forbidden calls.
- Prove reader/runner/admin, per-resource, team, workflow, cookie, claims,
  user-isolation, and service-account paths.
- Enable audience verification and observe the mismatched audience rejected.
- Use construction smoke for WorkOS only when its external credentials are
  unavailable.

### 08_os_config

- Fetch `/config` from both the Python and YAML examples.
- Verify explicit component IDs, labels, quick prompts, available models,
  named domains, and YAML `db_ids` match the constructed databases.

### 09_serving_workflows

- Boot each workflow server, inspect `/health`, `/config`, and workflow
  metadata, then run the paired REST/SSE client.
- Exercise the real workflow WebSocket route at `/workflows/ws`; do not treat
  agent or team SSE as WebSocket coverage.

### 10_knowledge

- Boot the single-knowledge server and inspect `/health`, `/config`, and its
  registered knowledge source.
- Upload content through `/knowledge/content`, poll its status, list and search
  it, delete it, and verify the deleted content is no longer readable.

### 11_learnings

- Run the learning-enabled agent with a stable user and immediately read the
  profile and memory it created through `/learnings`.
- Exercise create, list, users, get, update, delete, and bulk user cleanup with
  the current response schemas.

### 12_scheduler

- Start Postgres, boot the scheduler-enabled AgentOS, and observe a naturally
  due schedule create a successful run with real agent run and session IDs.
- Exercise REST CRUD, disable/enable, trigger, paginated history, and delete.
- Run sync and async `ScheduleManager` paths using `page`, not `offset`, and
  verify the SchedulerTools agent creates the intended default schedule.

### 13_observability

- Run one sync and one async agent call, read both traces through `/traces`,
  fetch their detail trees, and traverse nested `spans`.
- Verify `/traces/filter-schema`, advanced FilterExpr search, split trace-store
  routing with an explicit `db_id`, and `/metrics` refresh/readback.

### 14_mcp

- Boot each AgentOS MCP server with the current `mcp_server=` surface and
  inspect its registered MCP route.
- Use the live MCP client to discover and call tools, then exercise
  `continue_run` and `cancel_run` rather than leaving lifecycle calls as
  commented examples.
- Prove custom-tool registration and secure PAT authorization, including the
  service-account principal, host policy, tag filters, and full result mode.
- Construct and inspect both the built-in OAuth server and AuthKit
  bring-your-own authorization-server variants. Record construction smoke only
  when the required external credentials are unavailable.

### 15_a2a

- Boot the standalone agent and team servers on port 7779 and use only routes
  under `/a2a`.
- Run first-party client send, stream, multi-turn context threading, and
  unavailable-server handling.
- Read one agent card through both the synchronous and asynchronous client
  methods; verify stable identity and endpoint fields without advertising
  unsupported capabilities.
- Start the weather and Airbnb servers on ports 7782 and 7783, run the
  trip-planning orchestrator, and terminate all three processes.

### 16_agui

- Boot every file as a standalone server, assert `/health`, inspect `/config`,
  and verify its AG-UI status route.
- Confirm the configured AG-UI prefix serves `POST {prefix}/agui` and
  `GET /status`.
- Distinguish frontend-defined `external_execution` tools from real backend
  HITL with `requires_confirmation`.
- Verify tools, structured output, reasoning, Gemini media, shared state,
  research-team, and multiple-instance configurations.

### 17_slack

- Construct every Slack app with sentinel credentials, patch Slack
  `auth_test` to return synthetic bot identity, and verify `/health`,
  `/config`, plus each exact events and interactions route pair.
- Confirm every file documents both the Slack scopes and an in-Slack payoff.
- Verify streaming task cards, SlackTools workspace search, user-memory
  identity resolution, multi-bot prefixes, asymmetric peer-bot filtering, and
  all four HITL patterns.
- Run the focused Slack router, helper, filtering, security, media, tools, and
  route suites without sending a real workspace message.

### 18_telegram

- Construct all three examples with sentinel bot credentials and verify
  `/health`, `/config`, each status route, and each POST webhook route.
- Confirm the README documents commands, lazy command registration,
  `quoted_responses`, group mention filtering, session keys, media limits, and
  distinct webhook prefixes for multiple bots.
- Do not claim live command registration, delivery, inference, or media
  transfer without real provider credentials and a public HTTPS callback.

### 19_whatsapp

- Construct all five examples with sentinel Meta credentials and verify
  `/health`, `/config`, status, GET verification challenge, and POST webhook
  routes.
- Verify reply buttons, lists, locations, reactions, inbound and generated
  media, reasoning exposure, encryption and timeout documentation, and
  per-number prefixes.
- Confirm the multi-instance example documents that signature validation
  currently uses one process-wide `WHATSAPP_APP_SECRET`.

### 20_remote

- Start the AgentOS upstream on 7780 and Agno A2A upstream on 7781; verify
  health, config, and the A2A card before running the remote clients.
- Start Google ADK on 8001 and use its standard agent-card and JSON-RPC
  surfaces; do not invent AgentOS health or config endpoints for ADK.
- Exercise RemoteAgent call and stream, RemoteTeam, RemoteWorkflow, both A2A
  transports, remote Team membership, and all registered gateway paths.
- Restart the 7780 upstream with `OS_SECURITY_KEY`, observe an unauthenticated
  run rejected, and pass the key through `arun(auth_token=...)`.
- Verify the README distinguishes AgentOS RemoteAgent, A2A RemoteAgent, and
  raw A2AClient, and states current discovery/auth and parity limitations.

### 21_factories

- Boot every factory server, inspect discovery metadata, and run its `--demo`
  client.
- Verify factory identity override, database inheritance, forced event
  storage, fresh instances, and per-request cost guidance.
- Observe input-schema validation return HTTP 400 and
  `FactoryPermissionError` return HTTP 403.
- Verify trusted claims and scopes control RBAC and tier policy, then run the
  TeamFactory, WorkflowFactory, synchronous AgentFactory, and asynchronous
  AgentFactory paths.

### 22_studio

- Run the standalone StudioTools create, edit, version, and publish lifecycle
  against a synchronous SQLite database.
- Boot the AgentOS Studio servers and inspect registry primitives, code-defined
  components, and versioning tools.
- Exercise user-feedback, user-input, and confirmation pauses both on the
  console and through the AgentOS continue route.
- Call `GET /registry`, then create, read, update, and delete a component
  through `/components`; verify the sync-database requirement is documented.

### 23_skills

- Execute both checked-in sample-skill scripts directly and verify they exit 0
  with valid JSON output.
- Boot the Skills AgentOS, inspect `/health` and `/config`, and run the Agent
  through the REST API.
- Observe the Agent discover the `system-info` skill, call
  `get_skill_script(..., execute=True)`, and return real script output.
- Confirm the skill package contains `SKILL.md` and its scripts but no nested
  cookbook README or TEST_LOG.

### 24_showcase

- Start pgvector, load the Agno documentation knowledge, and boot the one
  capstone AgentOS with `OS_SECURITY_KEY`.
- Verify unauthenticated access is rejected, authenticated `/config` exposes
  the two distinct Agents and finance Team, and live runs exercise RAG,
  web/finance research, and Team coordination.
- Confirm tracing is enabled and read back the resulting trace.
- Run the checked-in `AccuracyEval` from `demo.py` and record its observed
  result; do not leave the evaluation commented out or replace it with a stub.

## Required validation

```bash
.venv/bin/pytest cookbook/scripts/tests/test_check_cookbook_pattern.py

.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/01_getting_started --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/02_databases --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/03_python_client --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/04_run_lifecycle --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/05_human_in_the_loop --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/06_customize --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/07_security --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/08_os_config --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/09_serving_workflows --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/10_knowledge --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/11_learnings --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/12_scheduler --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/13_observability --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/14_mcp --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/15_a2a --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/16_agui --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/17_slack --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/18_telegram --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/19_whatsapp --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/20_remote --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/21_factories --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/22_studio --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/23_skills --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/24_showcase --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os --recursive

source .venv/bin/activate
./scripts/format.sh
./scripts/validate.sh
git diff --check
```

Also reject stale models, deprecated AgentOS/MCP names, emojis, and non-final
test statuses in the root and lessons 01–24. Verify exactly 132 Python files,
exactly 24 numbered top-level lessons, no unnumbered topic directory, and all
363 migration rows. Report exact commands, observed results,
live-versus-construction coverage, and any library follow-up.
