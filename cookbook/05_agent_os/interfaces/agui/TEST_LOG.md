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

**Result:** Backend boots cleanly. AG-UI dojo's Tool Based Generative UI page connects, merges its frontend generate_haiku tool definition into the team's tool list, and the team calls generate_haiku with structured arguments (english, japanese, image_name, gradient) matching the dojo's render schema. Dojo renders haiku cards with theme-appropriate image + gradient for Nature, Ocean, and Spring prompts. Tool restraint verified (model answers "what is 2+2" with "4" without calling generate_haiku). Cross-framework comparison against LangGraph confirms output parity.

---
