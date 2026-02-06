# Teams HITL Cookbook Test Log

Last updated: 2026-02-06

## Test Environment
- Python: `.venv/bin/python`
- Command runner: `pytest`
- OpenAI key: not set in local environment

---

### libs/agno/tests/integration/teams/human_in_the_loop/test_run_requirement_fixes.py

**Status:** PASS

**Description:** Validates `RunRequirement` behavior fixes for confirmation/external execution state checks and member context serialization.

**Result:** 6/6 tests passed locally.

---

### libs/agno/tests/integration/teams/human_in_the_loop/test_team_confirmation_flows.py

**Status:** NOT RUN

**Description:** End-to-end team confirmation pause/continue scenarios.

**Result:** Requires model API credentials for execution.

---

### libs/agno/tests/integration/teams/human_in_the_loop/test_team_external_execution_flows.py

**Status:** NOT RUN

**Description:** End-to-end team external-execution pause/continue scenarios.

**Result:** Requires model API credentials for execution.

---

### libs/agno/tests/integration/teams/human_in_the_loop/test_team_user_input_flows.py

**Status:** NOT RUN

**Description:** End-to-end team user-input pause/continue scenarios.

**Result:** Requires model API credentials for execution.

---
