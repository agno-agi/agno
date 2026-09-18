# Test Log — Subagents

## 2026-07-23 — v-0.5 (`Agent(subagents_config=...)` / `Agent(enable_subagents=True)`)

### subagents_enabled.py

**Status:** PASS

**Description:** Agent(enable_subagents=True) - no config object. The agent gets a
default SubagentsConfig at init, so subagents inherit its model and tools. Asked for
two research topics; two parallel spawn_agent calls, both subagents searched
concurrently, parent synthesized a sourced answer.

**Result:** Working.

---

### subagents_combined_os.py

**Status:** PASS (import/build)

**Description:** One AgentOS app serving all four configuration styles: defaults via
enable_subagents, single model, named model options, and explicit allowed tools. App
builds with all four agents registered against one SqliteDb.

**Result:** Compiles, imports and builds the AgentOS app cleanly. Individual
configuration styles live-verified via their standalone cookbooks.

---

### subagents_defaults.py

**Status:** PASS

**Description:** Minimal setup - SubagentsConfig() with no options. Subagents inherit
the parent's model (single "default" option) and the parent's tools (websearch). Asked
for two research topics in parallel; the agent made two spawn_agent calls in one
response, both subagents searched concurrently, and the parent synthesized a final
answer with sources.

**Result:** Working. Note: in terminal output (aprint_response) the subagents' content
deltas render inline in the response panel since the CLI renderer does not nest by
parent_run_id; the AgentOS UI renders them as nested sub-agent runs.

---

### subagents_single_model.py

**Status:** PASS

**Description:** SubagentsConfig(model=OpenAIResponses(id="gpt-5.6-luna")) - a single
Model instead of an options dict. The config wraps it as the sole "default" option, so
the orchestrator (GPT-5.6 Terra) never picks a model and every subagent runs on Luna.
Asked for two research topics; two parallel spawn_agent calls, both subagents searched
concurrently, parent synthesized a sourced answer.

**Result:** Working.

---

### subagents_os.py

**Status:** PASS

**Description:** AgentOS research orchestrator (GPT-5.6 Terra) with subagents enabled
via SubagentsConfig (fast=GPT-5.6 Luna, deep=GPT-5.6 Terra). Verified live in the
AgentOS UI: spawn_agent calls run subagents in-process in the parent's session, their
events stream nested into the parent chat (tagged parent_run_id), model selection per
spawn works, tool result is the subagent's answer, nothing persisted.

**Result:** Working. A stream-level probe confirmed the event sequence is identical to
context-provider sub-agents (RunStarted/RunContent/RunCompleted with parent_run_id and
a distinct subagent agent_id, streaming live).

**Note:** Server auto-reload (`reload=True`) restarts uvicorn whenever watched files
change (including tool caches like .mypy_cache written during a run) and kills
in-flight runs mid-stream — if streaming looks broken, check for reload triggers first.

---

### coding_agent_os.py

**Status:** NOT RETESTED (on v-0.5)

**Description:** Coding orchestrator demonstrating an explicit allowed toolset:
SubagentsConfig(tools=[websearch, website, coding]) so subagents build and research
while FileGenerationTools and Workspace move/delete stay orchestrator-only. Compiles
and lints cleanly. Last full live run was on the v-1 toolkit API.

**Result:** Pending a live build-project run on the new API.

---

### Unit tests

`libs/agno/tests/unit/subagent/test_subagents.py` — 25 tests, all passing
(config defaults, model/tool selection and errors, child caching, event tagging,
session/state plumbing, cancel cascade, error paths, determine_tools_for_model
integration).
