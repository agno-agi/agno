# Steering — Test Log

### 01_steer_a_running_agent.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Streams a run, steers it from the `ToolCallStarted` event, and prints the `RunSteered` event and the combined answer.

**Result:** Compile verified. The delivery rules in the README are covered offline by `libs/agno/tests/unit/agent/test_agent_steering.py` (sync, async, stream, async stream) and `libs/agno/tests/unit/team/test_team_steering.py`.

---
