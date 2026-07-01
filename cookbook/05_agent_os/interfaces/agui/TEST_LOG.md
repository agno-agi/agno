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

### human_in_the_loop_send_email.py

**Status:** PASS

**Description:** HITL over AG-UI - backend confirmation (Shape B). A `send_email` tool gated by `requires_confirmation=True`; the human approves or declines a drafted email in the dojo, and on approval agno runs the tool server-side. Closes the confirmation / user_input gap that external-execution-only HITL leaves open.

**Result:** Live A/B verified on the dojo (backend on 127.0.0.1:9001, himanshu/agui-hitl worktree). Prompt "send an email to recipient@example.com" -> the agent drafts a subject/body and pauses -> the confirmation card renders (TOOL_CALL_START send_email -> TOOL_CALL_ARGS -> TOOL_CALL_END -> RUN_FINISHED paused, no result). Confirm -> agno runs send_email (DB: confirmed=True, result "Email sent to recipient@example.com with subject ...") and the agent confirms the send. Reject -> tool not run (DB: confirmed=False, result=None) and the agent acknowledges the email was not sent - visibly distinct from accept. Backed by unit tests: 14/14 in tests/unit/os/interfaces/test_agui_hitl.py (emission for confirmation / user_input / external pauses, pause-type-aware resolution incl. the single-shape user_input contract that fails loud on a malformed payload, the duplicate-tool-name dedupe, sync + async stream wrappers, and the partial-answer resume guard) and 69/69 in the full os/interfaces suite with zero regression. A 4-mutation matrix confirms the load-bearing tests are non-vacuous. ruff check + mypy clean (0 new errors) on the changed files. (Secrets/keys redacted; recipient is a placeholder.)

---
