# Antigravity cookbook test log

### antigravity_basic.py

**Status:** PENDING

**Description:** Smoke test — `AntigravityAgent.print_response("What is 2+2?", stream=True)`.

**Result:** Awaiting live-API verification with partner key.

---

### antigravity_session.py

**Status:** PENDING

**Description:** Two-turn session — turn 1 writes notes.txt in the sandbox, turn 2 reads it back; verifies environment_id is reused across turns.

**Result:** Awaiting live-API verification.

---

### antigravity_sources.py

**Status:** PENDING

**Description:** Provision a sandbox with an inline source file at /workspace/about.txt and ask the agent to read it.

**Result:** Awaiting live-API verification.

---

### antigravity_custom_agent.py

**Status:** PENDING

**Description:** POST /v1beta/agents to create a haiku-writing custom agent, then invoke it through AntigravityAgent.

**Result:** Awaiting live-API verification.

---

### antigravity_agentos.py

**Status:** PENDING

**Description:** Serve a AntigravityAgent through AgentOS; verify /agents list + streaming /runs.

**Result:** Awaiting live-API verification.

---

### antigravity_session_agentos.py

**Status:** PENDING

**Description:** Same as antigravity_agentos.py with SqliteDb-backed sessions; verify sessions persist across restarts.

**Result:** Awaiting live-API verification.

---

### antigravity_from_agent_directory.py

**Status:** PENDING

**Description:** Load an Antigravity agent from a local directory (`agent.yaml` + `AGENTS.md` + `workspace/` + `skills/`) via `AntigravityAgent.from_agent_directory()`. Auto-registers the named agent on first invocation. The `example_agent/` folder in this directory exercises all four layout elements.

**Result:** Unit tests pass for the directory parser (required-key validation, AGENTS.md precedence, workspace + skills targets, 75 KB size limit). Live cookbook run awaiting partner key.

---

### antigravity_snapshot.py

**Status:** PENDING

**Description:** Run a task that writes a file in the sandbox, then download the environment snapshot tar via `AntigravityAgent.download_environment_snapshot()`. Uses non-streaming because SSE doesn't expose `environment_id` (see open partner question).

**Result:** Unit tests pass for the snapshot toolkit method (env-id resolution from session_state, error surfacing). Live cookbook run awaiting partner key.

---

Note: the `AntigravityTools` toolkit example lives at `cookbook/91_tools/antigravity_tools.py` and is tracked in that folder's TEST_LOG.

---
