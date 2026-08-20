# Test Log - _03_persistence

Tested 2026-08-08 against `gpt-5.5` (OpenAIResponses), agno 3.0.0a1, ipykernel 7.3.0, dill 0.4.1, on `.venvs/demo`.

### basic.py

**Status:** PASS

**Description:** Snapshots into AgentFS over SqliteDb. The agent created `readings = [3, 1, 4, 1, 5, 9, 2, 6]` and `notes = 'first pass'` in the kernel. The script then called `close()` (flush a final snapshot) and `shutdown(SESSION_ID)` (kill the kernel), and asked a second question in the same session.

**Result:** Response in 6.1s after the kernel kill: "readings contains [3, 1, 4, 1, 5, 9, 2, 6], their sum is 31, notes contains the text 'first pass'." Both variables round-tripped through dill into the database and back into a brand-new kernel, and the sum is correct.

---

### developer_surface.py

**Status:** PASS

**Description:** The programmatic surface with no model involved: two cells, `variables()`, `value()`, and a deliberate `ZeroDivisionError`.

**Result:** Cell 1 returned `8` (list length); cell 2 printed "mean is 3.875" and returned `3.875`, proving state persisted across cells. `variables()` returned `{'statistics': 'module', 'readings': 'list', 'mean': 'float'}`. `value(SESSION_ID, "readings")` pulled `[3, 1, 4, 1, 5, 9, 2, 6]` into the host process by dill round trip. The `1 / 0` cell returned `status="error"` with `ZeroDivisionError: division by zero` in the traceback, and the following cell still returned `3.875` — the kernel survived the traceback as specified.

### Re-run 2026-08-19, after merging feat/v3.0

**Status:** PASS

**Description:** Both files in this folder were run again on the refreshed branch, against a live model. This is the check that the 47 commits merged in from feat/v3.0 did not break the feature.

**Result:** Same behaviour as the first run. No changes needed.

---
