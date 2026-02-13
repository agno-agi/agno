# Test Log -- 11_approvals

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### approval_async.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates approval async. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---

### approval_basic.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates approval basic. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---

### approval_external_execution.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates approval external execution. Ran successfully and produced expected output.
**Result:** Completed successfully in 4s.

---

### approval_list_and_resolve.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates approval list and resolve. Ran successfully and produced expected output.
**Result:** Completed successfully in 12s.

---

### approval_team.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates approval team. Assertion failed: AssertionError: Expected paused, got RunStatus.completed
**Result:** Code bug: AssertionError: Expected paused, got RunStatus.completed

---

### approval_user_input.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates approval user input. Ran successfully and produced expected output.
**Result:** Completed successfully in 6s.

---

### audit_approval_async.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audit approval async. Ran successfully and produced expected output.
**Result:** Completed successfully in 4s.

---

### audit_approval_confirmation.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audit approval confirmation. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---

### audit_approval_external.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates audit approval external. Assertion failed: AssertionError: Expected paused, got RunStatus.completed
**Result:** Code bug: AssertionError: Expected paused, got RunStatus.completed

---

### audit_approval_overview.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates audit approval overview. Assertion failed: AssertionError: Expected paused, got RunStatus.completed
**Result:** Code bug: AssertionError: Expected paused, got RunStatus.completed

---

### audit_approval_user_input.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audit approval user input. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---
