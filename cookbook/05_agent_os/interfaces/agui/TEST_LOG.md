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

**Status:** PASS

**Description:** Research Team - two members (researcher + writer) coordinated by a team leader, exposed over AG-UI. Demonstrates team member visibility via AG-UI Activity events.

**Result:** Verified end-to-end against the real AG-UI pipeline (run_entity -> event translation). Each member's progress is emitted as ACTIVITY_SNAPSHOT events (activity_type "agno.team_member") with a stable per-member message_id, agentId/agentName, status transitions (running -> tool_calling -> completed), and accumulated member text. Member text is NOT folded into the leader's TEXT_MESSAGE_* stream, which carries only the leader's own output. Validated with both a mocked-model harness and a real OpenAI-compatible model run; member tool calls produce tool_calling snapshots and the leader's final summary appears only in the leader message. Note: the model id was corrected to gpt-5.5 (the file previously referenced a non-existent gpt-5.4).

---

### state_events.py

**Status:** PENDING

**Description:** Outbound state synchronization via STATE_SNAPSHOT + STATE_DELTA events. Emits initial and final STATE_SNAPSHOT events plus STATE_DELTA JSON Patch ops after each state-mutating tool call.

---

### structured_output.py

**Status:** PENDING

**Description:** Structured Output.

---
