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

**Description:** Coordinate-mode Team exposes a team-level `external_execution=True` frontend tool (`generate_haiku`) through the AG-UI interface. Tool schema (`english`, `japanese`, `image_name`, `gradient`) matches the AG-UI dojo's `tool_based_generative_ui` page. `add_history_to_context=True` + `db=InMemoryDb()` persists prior turns so consecutive same-theme prompts vary their output. `external_execution_silent=True` suppresses the "Team run paused" status text.

**Result:** Tested against the PR #7819 branch (which adds the Team-side `TeamRunPausedEvent` handling, resume path, and silent-tool filter the dojo render relies on). Backend boots cleanly. AG-UI dojo's Tool Based Generative UI page connects, the team calls `generate_haiku` with structured arguments matching the dojo's render schema, the dojo executes the frontend handler and renders haiku cards for Nature, Ocean, and Spring prompts, and the team resumes on the posted-back tool result. Tool restraint verified (model answers "what is 2+2" with "4" without calling `generate_haiku`). End-to-end behavior on `main` will require PR #7819 to merge first.

The cookbook uses db=InMemoryDb() so add_history_to_context=True actually persists prior turns. Without a db, agno's Team silently drops history (warning: "add_history_to_context is True, but no database has been assigned to the team") and the model defaults to its strongest theme association on every call. SSE probe confirms Turn 3 input grows from 2 to 6 messages including the prior function_call. Mirrors LangGraph's state["messages"] semantic; canonical pattern per cookbook/06_storage/in_memory/.

Model: gpt-5.4 (per CLAUDE.md project standard). Reasoning model handles theme matching reliably -- ocean prompts always pick ocean-themed images (Itsukushima torii, Mount Fuji Lake), never the forest waterfall. Texts always vary across calls. Light pastel constraint in instructions keeps dark haiku text readable on every card.

Known limitation: image rotation within a single theme is best-effort. gpt-5.4 will sometimes pick the same image_name on consecutive same-theme prompts. LangGraph's reference integration exhibits the same behavior. A server-side post-processor that swaps repeated image_names would give a hard guarantee, but agno's external_execution flow does not natively expose a hook for outbound tool-arg mutation (entrypoint is not called for external tools, handle_external_execution_update only runs on resume). Out of scope for this cookbook; downstream consumers needing hard rotation can subclass the AGUI interface and override event emission.

---
