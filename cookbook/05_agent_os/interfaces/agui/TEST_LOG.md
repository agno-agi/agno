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

### workflow.py

**Status:** PASS

**Description:** Adaptive workflow over AG-UI -- a Router sends small talk to a non-streaming function step (chat_reply) and questions to streaming agent steps (research -> summarize). Exercises both completion-gate paths: a non-streamed function final (must be emitted exactly once) and a streamed agent final (must not be duplicated).

**Result:** Live-confirmed on the provenance completion gate via raw SSE (POST /agui), 2026-06-18. Small-talk path: the function reply renders in exactly one TEXT_MESSAGE delta (single START/END) then RUN_FINISHED. Research path: research+summarize stream into a single assistant message and the consolidated answer is NOT re-emitted -- there is no second TEXT_MESSAGE_START before RUN_FINISHED, i.e. the completion recap is suppressed. Backed by 70 unit tests (fail-before reproductions for drop/duplicate, a provenance-shape matrix, and real-engine StubModel regressions for stream_executor_events=False), mutation testing, and three adversarial skeptic passes (the last clean). Client-disconnect cancellation is covered by test_workflow_stream_stops_on_client_disconnect (the router path was unchanged by the gate rewrite).

**Known gaps (documented, not blocking):**
- A Loop/Parallel *final* step may duplicate a streamed answer: provenance is uncertain for fan-out, so the gate emits rather than risk a drop (drop-safe bias -- a rare duplicate beats a dropped answer).
- Upstream / engine (out of scope for this AG-UI interface): WorkflowCompletedEvent.content carries the cancellation reason on cancel; WorkflowRunEvent.condition_paused has no event class; CustomEvent.to_dict() raises for the synthetic custom event.

---
