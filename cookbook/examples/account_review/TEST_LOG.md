# Test Log — account_review

Tested September 16, 2026 with a fresh Python 3.14.5 environment installed from
this directory's `requirements.txt`: published Agno 3.0.8 and OpenAI 3.14.1.
Live calls used `gpt-5.6`, synthetic inputs, and disposable local storage.

### demo.py

**Status:** PASS

**Description:** Run the documented demo with the live model.

**Result:** The live workflow drafted the 30-to-18 user decline (40%), paused, and saved only after the test supplied approval. Deterministic workflow tests exercised both confirmation and rejection; a previously approved report stayed unchanged until confirmation and survived rejection. Only the drafting step was replaced by a fixture executor in those tests.

---

### test_contracts.py

**Status:** PASS

**Description:** Deterministic local contracts with no provider calls.

**Result:** 2 passed against published Agno 3.0.8; 2 passed against local
Agno 3.0.9 source at `37fc4121e3cf8863a2957b838fbad7c920bffe0f` selected via
`PYTHONPATH`. See the test file for the assertions and fixture boundaries.

---

No hosted deployment or production integration was tested.
