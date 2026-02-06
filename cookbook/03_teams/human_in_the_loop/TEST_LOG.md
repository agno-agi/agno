# Teams HITL Cookbook Test Log

Last updated: 2026-02-06

## Test Environment
- Python: `.venvs/demo/bin/python`
- Run command: `.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/<file>.py`
- Requires: `OPENAI_API_KEY` environment variable

---

### confirmation_required.py

**Status:** NOT RUN

**Description:** Demonstrates team pausing when a member agent's tool requires user confirmation. Shows the full pause/confirm/continue cycle with interactive prompts.

**Result:** Requires `OPENAI_API_KEY` and interactive terminal for Rich prompts.

---

### external_tool_execution.py

**Status:** NOT RUN

**Description:** Demonstrates external tool execution where the tool result is provided by the caller (e.g., actually sending an email). Shows pause/provide-result/continue cycle.

**Result:** Requires `OPENAI_API_KEY` and interactive terminal for Rich prompts.

---

### user_input_required.py

**Status:** NOT RUN

**Description:** Demonstrates collecting user input when a member agent's tool needs additional fields before execution. Shows pause/collect-input/continue cycle with schema-driven prompts.

**Result:** Requires `OPENAI_API_KEY` and interactive terminal for Rich prompts.

---
