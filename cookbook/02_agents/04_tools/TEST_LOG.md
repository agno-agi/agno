# TEST LOG

Generated: 2026-02-10 UTC

Pattern Check: Checked 3 file(s) in cookbook/02_agents/callable_factories. Violations: 0 (2 violations fixed: added section banners to 02_session_state_tools.py and 03_team_callable_members.py)

### 01_callable_tools.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### 02_session_state_tools.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### 03_team_callable_members.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### tool_call_limit.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### tool_choice.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

### 01_callable_tools.py

**Status:** PASS

**Description:** Callable tools factory with RunContext-based role dispatch. Viewer run resolved `search_web` only; admin run resolved all 3 tools. Tool calls `search_internal_docs` and `get_account_balance` executed correctly for admin.

**Result:** Completed successfully.

---

### 02_session_state_tools.py

**Status:** PASS

**Description:** Session state injection via `session_state` param name with `cache_callables=False`. Factory re-ran on each call, correctly switching between `get_greeting` (greet mode) and `get_farewell` (farewell mode).

**Result:** Completed successfully.

---

### 03_team_callable_members.py

**Status:** PASS

**Description:** Team with callable `members` factory. Writer-only mode delegated to Writer agent. Researcher+Writer mode delegated to both via `delegate_task_to_member`. Team coordination completed in ~32s.

**Result:** Completed successfully.

---

---

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

Pattern Check: Checked 8 file(s) in cookbook/02_agents/run_control. Violations: 0

### retries.py

**Status:** PASS

**Description:** Demonstrates retry mechanism with `num_retries` and `retry_delay_seconds` using web search tools.

**Result:** Completed successfully. Agent responded about AI agents with web search, no retries needed (no failure triggered).

---

### metrics.py

**Status:** PASS

**Description:** Shows how to retrieve run, message, and session metrics. Uses PostgresDb and YFinanceTools.

**Result:** Completed successfully. Metrics printed including token counts, duration (23.9s), and cache metrics.

---

### cancel_run.py

**Status:** PASS

**Description:** Demonstrates cancelling a running agent with threading. Uses RunEvent.run_cancelled and RunStatus.

**Result:** Completed successfully. Run was cancelled mid-generation. Status correctly showed "cancelled" with partial content.

---

### tool_call_limit.py

**Status:** PASS

**Description:** Controls max number of tool calls with `tool_call_limit`. Uses YFinanceTools with `gpt-4o-mini`.

**Result:** Completed successfully. Agent used tool calls within the limit to get TSLA stock price ($426.15). Previous FAIL (Anthropic key) resolved — cookbook now uses OpenAI models.

---

### agent_serialization.py

**Status:** PASS

**Description:** Agent serialization/deserialization via `.to_dict()` / `.from_dict()` and `.save()` / `.load()`. Uses `OpenAIResponses(id="gpt-5.2")`.

**Result:** Completed successfully. Agent serialized, deserialized, saved to DB, and loaded back. Loaded agent responded correctly.

---

### debug.py

**Status:** PASS

**Description:** Demonstrates `debug_mode` flag (both global and per-run).

**Result:** Completed successfully. Debug output visible, joke response generated.

---

### tool_choice.py

**Status:** PASS

**Description:** Controls tool invocation strategy: `none`, `auto`, or forced choice. Uses `OpenAIResponses(id="gpt-5.2")`.

**Result:** Completed successfully. All 3 tool choice modes demonstrated correctly. Previous FAIL (Anthropic key) resolved — cookbook now uses OpenAI models.

---

### concurrent_execution.py

**Status:** PASS

**Description:** Concurrent agent execution using `asyncio.gather` with a single shared agent instance. Generates reports on multiple AI providers.

**Result:** Completed successfully. 3 concurrent runs completed with distinct reports for OpenAI, Anthropic, and Google.

---
