# Test Log - _09_task_selection

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Metadata-based selection of original environment tasks.

**Result:** Metadata selection ran two of the three environment tasks.
`calibration-a` passed 3/4 (0.75) and `calibration-b` 4/4 (1.00); the held-out
`smoke` task was not executed.

---

### rerun_failures.py

**Status:** PASS

**Description:** Initial grid followed by a targeted rerun of every row below a full pass rate.

**Result:** The initial grid scored `easy-anchor` 4/4 (1.00),
`rerun-edge-a` 4/4 (1.00), and `rerun-edge-b` 3/4 (0.75). Only
`rerun-edge-b` was selected for the second batch, where it scored 2/4 (0.50).
Both batches therefore contained a true partial binary pass-rate row.

---
