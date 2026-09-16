# Test Log — task_agent

Tested September 16, 2026 with a fresh Python 3.14.5 environment installed from
this directory's `requirements.txt`: published Agno 3.0.8 and OpenAI 3.14.1.
Live calls used `gpt-5.6`, synthetic inputs, and disposable local storage.

### demo.py

**Status:** PASS

**Description:** Run the documented demo with the live model.

**Result:** The live agent listed Alice's task, called `complete_task(task_id=task-1)`, recalled completion, and called `complete_task(task_id=task-2)`, which returned not found. Contract checks verified Bob's task stayed unchanged and repeated completion was idempotent.

---

### test_contracts.py

**Status:** PASS

**Description:** Deterministic local contracts with no provider calls.

**Result:** 1 passed against published Agno 3.0.8; 1 passed against local
Agno 3.0.9 source at `37fc4121e3cf8863a2957b838fbad7c920bffe0f` selected via
`PYTHONPATH`. See the test file for the assertions and fixture boundaries.

---

No hosted deployment or production integration was tested.
