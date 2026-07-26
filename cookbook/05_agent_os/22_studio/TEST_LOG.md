# Test Log: 22_studio

Tested live on 2026-07-24 against Agno source commit
`45bfff9f2aa6ec11b7386c3cd3bf6d1141d005dc`.

Every process loaded Agno from this worktree through
`PYTHONPATH=/Users/ab/code/worktrees/agno-agent-os-rewrite/libs/agno`.
Provider credentials were loaded with `direnv exec .`; no credential values
were recorded. Server-backed examples used port `7792` to avoid interfering
with other AgentOS lessons, and the listener was stopped after every run.

### standalone_studio_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran a standalone Claude Studio Agent with Registry discovery,
SQLite component persistence, and `StudioTools(versions=True)`. The Agent
listed registered models and tools, created an Agent, edited it to a draft,
listed both versions, and published the draft.

**Result:** Run `5e61007c-7f6f-4611-be11-8ce2dd58468b` completed with exact
model ID `claude-sonnet-4-6`. Component `studio-math-tutor-9794e075` progressed
from published v1 to draft v2 and then published v2; v2 became current.

---

### studio_tools_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS on port `7792`, checked health plus Registry
and Components discovery, then asked the live Studio Agent to discover the
registered model, tool, and database and create one persisted Agent.

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
discovery plus the Components create, read, filtered-list, update,
current-config, and delete endpoints with real HTTP requests.

**Result:** Registry discovery returned all five registered resources,
including both current model IDs, `calculator`, and the SQLite database.
Component `registry-crud-agent-fa59682f` was created as published v1, renamed,
read through `/configs/current`, deleted with HTTP 204, and confirmed absent
with HTTP 404.

---

## Validation

- All five Python targets passed worktree-pinned compilation and targeted Ruff
  format/check.
- Recursive inventory and pattern validation checked exactly five Python files
  with zero violations.
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
- `git diff --check` passed for the rewritten and deleted paths.
