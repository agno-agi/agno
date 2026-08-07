# Test Log: 22_studio

This file keeps historical live evidence separate from validation of the typed
StudioTools 2.9 migration. The historical results below prove the examples that
existed at those pinned revisions; they do not validate the current API.

## Typed StudioTools 2.9 migration validation

**Status:** PASS

**Test mode:** LOCAL CONSTRUCTION + FOCUSED TESTS + LIVE POSTGRESQL

**Date:** 2026-08-11

Validated the seven Python targets against the final three-branch StudioTools
2.9 stack in the `codex/studio-schedule-runtime-v2` worktree after rebasing its
three single-commit layers onto `main` at
`26bb90c612e94aeb32f46ba42ac541ded713e817`. The rebase retained the exact
50/23/11-file layer boundaries; the only overlap is the two-file transition
bridge that the typed control-plane layer replaces. It reconciled the final
StudioRunner hardening and the selected-workflow-version WebSocket fix that
landed on `main`, including fail-closed graph limits, occurrence-specific pins,
declared model/database fidelity, code-only discovery, and shadow-safe totals.
Every module was executed through
`runpy.run_path(..., run_name="studio_validation")`, which exercises imports,
toolkit construction, typed component seeding, SQLite persistence, and AgentOS
app construction without entering each script's provider-backed `__main__`
path.

**Result:**

- all seven Python files passed source compilation with the demo Python
  runtime;
- all seven passed targeted Ruff check and format validation;
- all seven passed construction-only execution;
- `studio_runner_direct.py` construction created published Agent, Team, and
  Workflow components from `AgentCreate`, `TeamCreate`, and `WorkflowCreate`;
- the consolidated predecessor-preservation, Studio, runner, component-router,
  scheduler, authorization, serialization, SQLite lifecycle, and migration
  matrices passed all `1519` tests;
- the live PostgreSQL lifecycle, migration, and Studio integration matrix
  passed all `32` tests, including immutable version payloads, guarded
  publication, rollback projection, dependency cycles, and concurrent writes;
- the current-main composition pass added `18` workflow-run integration tests
  and `106` draft-visibility, workflow-config, and component-save tests;
- after hosted CI exposed PostgreSQL constructor test-double and stale
  implicit-reactivation assumptions, all `99` affected constructor, schema,
  auth-token, component-archive, and serialization unit tests passed;
- `./scripts/format.sh` and `./scripts/validate.sh` passed, including core and
  agnoctl mypy, Ruff for every package, and cookbook validation;
- `git diff --check` passed for the current worktree.

Earlier in this migration pass, before the authoritative base advanced, the
direct runner, standalone lifecycle, and JWT-authenticated AgentOS examples
also completed live runs `c162c8ea-9b19-44b2-acd5-eb64068331c4`,
`bcb0d1b4-4708-4dc1-9b00-99ff1f4984db`, and
`b10eddea-a02c-4885-a5cf-637605b40697`. Those provider-backed runs were not
repeated after the base refresh, so they are supporting evidence rather than
proof of the final stacked source. The two HITL examples and
`registry_and_components.py` were likewise construction-tested but not rerun
end to end; their older live results remain below as historical evidence.

## Historical live validation

The first five entries and the historical Validation section record the
2026-07-24 pass against Agno source commit
`45bfff9f2aa6ec11b7386c3cd3bf6d1141d005dc`, loaded through
`PYTHONPATH=/Users/ab/code/worktrees/agno-agent-os-rewrite/libs/agno`. The two
`studio_runner_*` entries record the 2026-08-06 pass against the
`feat/studio-runner-tools` worktree; each carries its own provenance.

Provider credentials were loaded with `direnv exec .`; no credential values
were recorded. Server-backed examples used port `7792` to avoid interfering
with other AgentOS lessons, and the listener was stopped after every run.

### standalone_studio_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran a standalone Claude Studio Agent with Registry discovery,
SQLite component persistence, and the then-current pre-2.9 StudioTools
contract. The Agent listed registered models and tools, created an Agent,
edited it to a draft, listed both versions, and published the draft.

**Result:** Run `5e61007c-7f6f-4611-be11-8ce2dd58468b` completed with exact
model ID `claude-sonnet-4-6`. Component `studio-math-tutor-9794e075` progressed
from published v1 to draft v2 and then published v2; v2 became current.

---

### studio_tools_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS on port `7792`, checked health plus Registry
and Components discovery, then asked the live Studio Agent to use the
then-current flat request contract to create one persisted Agent.

**Result:** Run `967a66e1-b258-41ba-82b4-e800b76f9242` completed. Component
`api-math-guide-147c45ec` was stored as published v1 with `gpt-5.5`, the exact
registered `calculator` toolkit, and the registered `studio-tools-db`.

---

### studio_hitl_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the console Studio Agent with an underspecified create
request and resolved every `RunRequirement` through `Agent.continue_run`.

**Result:** Run `90860bfe-c585-47be-a86f-3561929c9548` paused exactly once for
structured user feedback, once for free-text user input, and once for
confirmation, in that order. After approval it completed and persisted
`console-research-buddy-2cb46ffb` with the selected `calculator` toolkit.

---

### studio_hitl_agent_os.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS on port `7792`, submitted an underspecified
Agent run over HTTP, and continued the same run by round-tripping the updated
serialized tool payload through the Agent continuation endpoint.

**Result:** Run `6e96543b-9c28-4dfb-9bd0-b6662c6634f7` exposed exactly the
feedback, input, and confirmation pauses in order, then completed. The
confirmed call persisted `os-research-buddy-75a4e73f` with the selected
`calculator` toolkit and `studio-hitl-agentos-db`.

---

### registry_and_components.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS on port `7792` and exercised Registry
discovery plus the then-current Components create, read, filtered-list,
update, current-config, and removal endpoints with real HTTP requests.

**Result:** Registry discovery returned all five registered resources,
including both current model IDs, `calculator`, and the SQLite database.
Component `registry-crud-agent-fa59682f` was created as published v1, renamed,
read through `/configs/current`, removed through the historical router contract,
and confirmed absent. This is provenance for that pinned revision, not current
StudioTools lifecycle guidance.

---

### studio_runner_dispatcher.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Tested 2026-08-06 against the `feat/studio-runner-tools`
worktree via `PYTHONPATH=/Users/ab/code/agno-worktrees/studio-runners/libs/agno`.
Built a Haiku Writer component with StudioTools, then asked a runner-only
Dispatcher Agent to discover and delegate to it through StudioRunnerTools.

**Result:** The dispatcher called list_agents/list_teams/list_workflows, then
run_agent(agent_id=haiku-writer) and returned the delegated haiku. No mutation
tools were exposed to the dispatcher.

---

### studio_runner_direct.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Tested 2026-08-06 against the `feat/studio-runner-tools`
worktree. Called StudioRunnerTools methods directly: list_agents, run_agent by
exact id, and a registry-less run_agent against a tool-bearing component.

**Result:** Listing returned both built components, the greeter run completed
with content, and the registry-less runner refused the calculator agent with
"references registry-backed resources (tools); construct StudioRunnerTools
with the registry to run it."

---

## Historical Validation (2026-07-24 pass)

- All five Python targets of that pass passed worktree-pinned compilation and
  targeted Ruff format/check; the two 2026-08-06 `studio_runner_*` additions
  were format/pattern-checked in their own pass (seven files total now check
  clean).
- The focused StudioTools, Registry-router, and Components-router unit suites
  passed all 157 tests.
- All five capability-specific examples were executed live; the two HITL
  examples proved real pause/continue behavior and the Registry example proved
  actual component CRUD.
- Every temporary listener on port `7792` was stopped after its client
  completed.
- App construction emitted the current-source duplicate `get_config` OpenAPI
  operation-ID warning for component configuration routes; no lesson code
  overrides framework route metadata.
- The assigned legacy `studio_tool/` lesson was removed after all replacements
  passed.
- `git diff --check` passed for the rewritten and removed paths.
