# dynamic_subagent — Test Log

> **Environment:** OpenAI Responses API (`gpt-5.4` / `gpt-5.4-mini`).
> Cookbooks that use `DuckDuckGoTools` (02, 03, 04) require `ddgs` (`pip install ddgs`).
> Run with: `PYTHONIOENCODING=utf-8 .venvs/demo/bin/python cookbook/02_agents/18_dynamic_subagents/<file>.py`

---

### 01_basic.py

**Status:** PASS

**Description:** Orchestrator with `enable_dynamic_subagents=True` and no `SubAgentConfig`.
The LLM decided on its own to use `spawn_agent` for two independent writing subtasks
(poem + history explanation). The orchestrator's response contained only the final
combined answer — no intermediate tool outputs visible in the parent context.

**Result:** Agent ran in ~10s. Lifecycle logs showed spawn + completion with token counts.
Context isolation confirmed — parent context contained only the final answer.

---

### 02_with_tools.py

**Status:** PASS

**Description:** Orchestrator delegates `DuckDuckGoTools` to subagents via `allowed_tools`
whitelist (`["duckduckgo_search", "duckduckgo_news"]`). Two subagents were spawned — one
for quantum computing research, one for AI safety news. Each subagent ran web searches
internally; the orchestrator received only the summaries.

**Result:** Agent ran in ~5s. Tool whitelist filtering worked — subagents received only
the permitted functions, not the full toolkit. Combined summary returned correctly.

---

### 03_parallel.py

**Status:** PASS

**Description:** Three async subagents spawned concurrently in a single LLM turn via
`aprint_response`. Subagents researched Python 3.13 features, latest Rust release notes,
and WebAssembly news in parallel. All three ran within `max_concurrent=3`.

**Result:** Agent ran in ~75s (web searches). All three subagents spawned and completed
concurrently — lifecycle logs confirmed simultaneous spawning. Orchestrator combined
the three research summaries into a single coherent response.

---

### 04_team.py

**Status:** PASS

**Description:** A `Team` with `enable_dynamic_subagents=True` alongside registered
`researcher` and `writer` members. Team leader spawned a subagent to handle heavy
data-fetching; permanent members handled the writing task.

**Result:** Team ran in ~9.5s. Spawned subagent correctly carried `team_id` in metadata
(confirmed via lifecycle logs at `depth=1`). Team leader's context stayed clean — only
the subagent's summary entered the team conversation, not the raw web results.

---

### 05_model_tiers.py

**Status:** PASS

**Description:** Cost-aware orchestrator with three tiers (`fast → gpt-5.4-mini`,
`standard → gpt-5.4`, `powerful → o3`). LLM routed simple number extraction to
`fast`, paragraph explanation to `standard`, and architecture trade-off analysis to
`powerful`. Re-run required after the `OpenAIResponses`/`gpt-5.4` migration; tier
selection logic and guidance injection were verified against the new model IDs.

**Result:** Agent ran in ~16s. LLM correctly selected tier labels per task type.
`model_tier` routing through `_resolve_model` confirmed in lifecycle logs. Tier guidance
visible in spawned subagent `instructions`.

---

### 06_context_isolation.py

**Status:** PASS

**Description:** Customer support scenario with mock `CustomerDataTools` (returns 50-order
JSON blob) and `KnowledgeBaseTools` (returns multi-section policy article). Both tools
are registered on `context_heavy_tools` so the orchestrator is guided to always route
them through `spawn_agent`.

**Result:** Agent ran in ~27s. Orchestrator spawned two subagents — one for order lookup,
one for policy search. Each subagent processed the large tool payload internally;
the orchestrator's context only received two short summaries (~50 tokens each) instead
of the full JSON and policy article. Final response correctly combined order details
with return policy instructions.

---
