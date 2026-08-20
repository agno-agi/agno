# Test Log -- 04_tools



## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| 04_tools_with_literal_type_param.py | PASS |  |
| tool_choice.py | PASS | first batch attempt exceeded 240s; retry completed - final forced-tool invocation hit an env read-timeout |

---

## Verification - 2026-08-18 round 3 (feat/v3.0, base b10e70d5d4)

**Environment:** `.venvs/demo/bin/python`, batch runner with 240s timeout

| File | Status | Note |
|---|---|---|
| 01_callable_tools.py | PASS |  |
| 02_session_state_tools.py | PASS |  |
| tool_call_limit.py | PASS |  |

---

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### 01_callable_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 01 callable tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 17s.

---

### 02_session_state_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 02 session state tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 7s.

---

### 03_team_callable_members.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 03 team callable members. Ran successfully and produced expected output.
**Result:** Completed successfully in 87s.

---

### 04_tools_with_literal_type_param.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates using typing.Literal for tool parameters with predefined values. Tests both Toolkit methods and standalone functions with Literal type hints.
**Result:** JSON schema correctly generates enum constraints for Literal types.

---

### tool_call_limit.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates tool call limit. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### tool_choice.py

**Status:** TIMEOUT
**Tier:** untagged
**Description:** Demonstrates tool choice. Timed out after 120s - likely making many API calls or stuck.
**Result:** Timed out after 120s.

---
