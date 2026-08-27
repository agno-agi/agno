# Test Log: 22_studio

All seven examples record the 2026-08-18 live pass for the Studio 3.0 rewrite
(draft-by-default lifecycle, StudioResult envelopes, archive/restore), against
worktree commit `9ea0b121a` on branch `feat/studio-3.0`, loaded through
`PYTHONPATH=/Users/ab/code/worktrees/agno-studio-3.0/libs/agno` with
`.venvs/demo/bin/python`. Provider credentials came from the shell environment;
no credential values were recorded. Server-backed examples listened on port
`7777` and every listener was stopped after its run.

### standalone_studio_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** The LLM-driven 3.0 ladder plus the direct-Python section. The
Claude agent discovered exact registry names, created a draft agent, validated
it, previewed the draft with `run_agent(version=1)`, published v1, appended a
draft v2 via `edit_agent`, listed both versions, and published v2. The direct
section then composed a workflow with a compound `loop` step, validated it,
appended a guarded edit, and hit the stale-guard refusal.

**Result:** Component `studio-math-tutor-93854a91` reached current version 2
with stages `['published', 'published']`; preview run answered 42 before any
publish. Direct section: `claim-review-8da0941f` validated, guarded edit
appended v2, stale guard returned `version_conflict` with `retryable: true`.

---

### studio_tools_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Served the AgentOS app, then ran the `--demo` HTTP client:
POST to the studio agent's run endpoint as `studio-demo-user`, instructing a
`publish=true` create.

**Result:** Run `3a330d26` COMPLETED; component `api-math-guide-8ce75a74` v1
published, `ComponentResponse.user_id` reported owner `studio-demo-user`.

---

### studio_hitl_agent.py

**Status:** PASS

**Test mode:** LIVE (`--auto`)

**Description:** Console HITL flow: the run paused for user feedback, then a
user-input form (tool selection + instructions), then confirmation of the
gated `create_agent`, resolved deterministically.

**Result:** Pause sequence `['user_feedback', 'user_input', 'confirmation']`;
final run COMPLETED; `console-research-buddy-b1d193fb` created as a draft
(stages `['draft']`, no current version) owned by `console-hitl-user`.

---

### studio_hitl_agent_os.py

**Status:** PASS

**Test mode:** LIVE (server + `--demo`)

**Description:** The same three-pause HITL flow driven through the AgentOS
REST API with `user_id` form fields on run and continue.

**Result:** Pause sequence `['user_feedback', 'user_input', 'confirmation']`;
run `d8363ead` COMPLETED; `os-research-buddy-6974b5d3` created as an
unpublished draft owned by `agentos-hitl-user`.

---

### registry_and_components.py

**Status:** PASS

**Test mode:** LIVE (server + `--demo`)

**Description:** The 3.0 REST lifecycle end to end: create a draft, confirm
the draft-only component returns 404 on the public run endpoint, append a
config with a version guard, hit 409 on a stale guard, publish v2, rename,
archive (DELETE -> 204, GET -> 404), and restore.

**Result:** `registry-lifecycle-agent-386f6b59`: draft dispatch 404 before
publish; guarded append produced v2 and the stale guard 409'd; archive then
restore brought the component back at v2. Registry reported 5 resources.

---

### studio_runner_direct.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Created and published two agents through StudioTools
envelopes, listed them via `StudioRunnerTools`, ran one live, and demonstrated
the registry-guard refusal on a runner constructed without the registry.

**Result:** Live run COMPLETED. The registry-less refusal named the exact
missing tool functions (`add` ... `square_root`) and noted that reads and
edits still load the component.

---

### studio_runner_dispatcher.py

**Status:** PASS

**Test mode:** LIVE

**Description:** A dispatcher agent holding only `StudioRunnerTools` listed
agents/teams/workflows and dispatched the published `haiku-writer` on request.

**Result:** `run_agent(agent_id=haiku-writer, ...)` COMPLETED and returned a
haiku; discovery listed only what dispatch admits.

### registry_learning.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Added 2026-08-21 for the learning-in-Studio change, run from
worktree branch `feat/learning-in-studio` via
`PYTHONPATH=<worktree>/libs/agno .venv/bin/python` (the demo venv was not
present on this machine). Declared two `LearningMachine`s on the Registry
(`shared-brain` / `research-brain`, namespaces `shared` / `research`, model
declared), listed them with `list_learning`, created the published
`profile-coach` agent with `learning_name="shared-brain"`, read the stored
config, requested an undeclared name, rehydrated the agent through
`get_agent_by_id`, ran it as user `ash`, then detached with `learning_name=""`.

**Result:** `list_learning` printed both machines with per-store modes and
namespaces; the stored config carried `{'name': 'shared-brain'}` (a reference,
not the machine); `get_component` showed `learning_name: shared-brain`;
`my-own-brain` was refused with `learning_not_found`; the rehydrated agent held
the same machine object (`agent.learning is shared_brain: True`) with
`SqliteDb` injected and `gpt-5.5` as declared on the machine; the tool list for user `ash` included
`update_user_memory` plus the entity tools, and without a user only the entity
tools. The live run called `update_user_memory(task=User's name is Ash.)` and
answered "Got it, Ash."; the detach wrote a version with no `learning` key.

---

**Addendum (same day):** the `enable_learning=True` section was added after the
live pass and verified in a key-less re-run of the same file (the section needs
no provider): `note-taker` stored `learning: True`, rehydrated through
`get_agent_by_id`, and `initialize_agent` produced the default machine with
`user_profile` + `user_memory` on `gpt-5.5`; the rest of the output matched the
live pass.

---
