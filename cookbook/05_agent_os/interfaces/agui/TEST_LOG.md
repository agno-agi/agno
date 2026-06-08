# Test Log: interfaces/agui

> Tests not yet run. Run each file and update this log.

### agent_with_media.py

**Status:** PASS

**Description:** Agent With Media - AG-UI agent (Google Gemini) that accepts multimodal user input.

**Result:** AgentOS boots with the AG-UI interface; /config returns 200. Media sent through POST /agui reaches the Gemini agent, which describes it accurately - verified with an image via CLI and interactively in a browser. Multimodal input path verified end-to-end.

---

### agent_with_silent_tools.py

**Status:** PENDING

**Description:** Silent External Tools - Suppress verbose messages in frontends.

---

### agent_with_tools.py

**Status:** PENDING

**Description:** Agent With Tools.

---

### basic.py

**Status:** PENDING

**Description:** Basic.

---

### multiple_instances.py

**Status:** PENDING

**Description:** Multiple Instances.

---

### reasoning_agent.py

**Status:** PENDING

**Description:** Reasoning Agent.

---

### research_team.py

**Status:** PENDING

**Description:** Research Team.

---

### state_events.py

**Status:** PENDING

**Description:** Outbound state synchronization via STATE_SNAPSHOT + STATE_DELTA events. Emits initial and final STATE_SNAPSHOT events plus STATE_DELTA JSON Patch ops after each state-mutating tool call.

---

### structured_output.py

**Status:** PENDING

**Description:** Structured Output.

---

### team_with_tools.py

**Status:** PASS

**Description:** Team With Tools - coordinate-mode Team with a team-level external_execution frontend tool (generate_haiku) registered via the AG-UI interface. Exercises the Team-side variants of the #7801 frontend-tool merge fix and the Bug 1/2/3/4 hardening from PR #7819.

**Result:** Backend boots cleanly. AG-UI dojo's Tool Based Generative UI page connects, merges its frontend generate_haiku tool definition into the team's tool list, and the team calls generate_haiku with structured arguments (english, japanese, image_name, gradient) matching the dojo's render schema. Dojo renders haiku cards for Nature, Ocean, and Spring prompts. Tool restraint verified (model answers "what is 2+2" with "4" without calling generate_haiku). Cross-framework comparison against LangGraph confirms output parity.

Image-diversity hardening: added db=InMemoryDb() so add_history_to_context=True actually persists prior turns. Without a db, agno's Team silently drops history (warning: "add_history_to_context is True, but no database has been assigned to the team") and the model defaults to its strongest theme association every call. SSE probe confirms Turn 3 input grows from 2 to 6 messages including the prior function_call. Mirrors LangGraph's state["messages"] semantic; canonical pattern per cookbook/06_storage/in_memory/.

Model: gpt-5.4 (per CLAUDE.md project standard). Reasoning model handles theme matching reliably -- ocean prompts always pick ocean-themed images (Itsukushima torii, Mount Fuji Lake), never the forest waterfall. Texts always vary across calls.

Gradients: light pastel constraint in instructions keeps dark haiku text readable on every card. Verified across nature, ocean, spring prompts -- gradient color family alternates naturally and never collapses to dark/oversaturated.

Known limitation: image rotation within a single theme is best-effort. gpt-5.4 will sometimes pick the same image_name on consecutive same-theme prompts (e.g., two "nature haiku" requests in a row may both return Takachiho). LangGraph's reference integration exhibits the same behavior. A server-side post-processor that swaps repeated image_names would give a hard guarantee, but agno's external_execution flow does not natively expose a hook for outbound tool-arg mutation (entrypoint is not called for external tools, handle_external_execution_update only runs on resume). Out of scope for this cookbook; downstream consumers needing hard rotation can subclass the AGUI interface and override event emission.

---
