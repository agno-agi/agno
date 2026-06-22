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

### workflow_progress.py

**Status:** PASS

**Description:** Native-first workflow progress over AG-UI -- a sequential Workflow (research -> analyze -> summarize) whose live progress renders from `state.workflow_progress.steps` ({name, status, step_index, output}) via STATE_SNAPSHOT/STATE_DELTA + native STEP_STARTED/FINISHED, with ZERO structural CustomEvent. The "simple case" unlocked by the native-first rework.

**Result:** Verified end-to-end. The sequential workflow's progress renders live from `state.workflow_progress.steps` in the AG-UI Dojo (agentic_generative_ui feature, via useCoAgentStateRender) -- the panel fills research -> analyze -> summarize to 3/3 Complete -- with no custom-event handling on the client. Raw SSE confirms the wire: STATE carries workflow_progress.steps, native STEP fires, zero structural CustomEvent.

**Verification:**
- Unit: 98 agui interface tests pass (workflow + router + state_events); 5/5 key mutations re-proven (custom_event exclusion, _finalize_run re-inject, mark_completed promotion, strip on BOTH save paths, enum-driven RAW coverage); cheat-detector clean; ruff clean; mypy 0 introduced (base-comparison vs #8364). (DONE)
- Core: 410 workflow tests pass (7 pre-existing skips) -- transient strip non-regressing on save/load. (DONE)
- Raw SSE (4.1): POST /agui -> 2 STATE_SNAPSHOT, 7 STATE_DELTA, 3 STEP_STARTED, 3 STEP_FINISHED, CUSTOM=0; workflow_progress.steps on the wire. (DONE -- PASS)
- Live render (4.2): state.workflow_progress.steps renders and updates in the Dojo; 3/3 Complete observed (screenshot on file). (DONE -- PASS)
- Robustness (4.3): loop/parallel/condition/router/nested populate the flat steps[] with no structural CUSTOM/RAW; step_error -> "error" (no RUN_ERROR); cancel -> "cancelled"; pause -> "paused"; no-state baseline emits a leading STATE_SNAPSHOT (real-engine unit tests). Concurrency isolation: two sessions run concurrently with no progress bleed. (DONE -- PASS)
- A/B (4.4): agent/team AG-UI paths unchanged -- 15 router + state_events tests pass. (DONE -- PASS)

**Known gaps (honest):**
- Postgres not run live -- the transient strip is backend-agnostic by construction (pops the key before the DB driver in both save_session/asave_session); verified on sqlite sync + async, not Postgres.
- Topology grouping (parallel/loop/condition/router rendered flat, not nested) deferred to the follow-up.
- Interactive pause/resume (HITL) deferred; pause shows as a status label only.

---
