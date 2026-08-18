# Test Log -- 01_quickstart



## Verification - 2026-08-18 round 3 (feat/v3.0, base b10e70d5d4)

**Environment:** `.venvs/demo/bin/python`, batch runner with 240s timeout

| File | Status | Note |
|---|---|---|
| agent_with_instructions.py | PASS |  |

---

## Verification - 2026-08-18 (feat/v3.0)

**Environment:** `.venvs/demo/bin/python` | **Base Commit:** `b10e70d5d4` (feat/v3.0 merged)

### basic_agent.py

**Status:** PASS

**Description:** Minimal agent run.

**Result:** Response rendered, clean exit.

---

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### agent_with_instructions.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates agent with instructions. Ran successfully and produced expected output.
**Result:** Completed successfully in 9s.

---

### agent_with_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates agent with tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 6s.

---

### basic_agent.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates basic agent. Ran successfully and produced expected output.
**Result:** Completed successfully in 2s.

---
