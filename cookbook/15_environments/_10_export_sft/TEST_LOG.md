# Test Log - _10_export_sft

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Ran two arithmetic tasks four times, selected both learning-zone
rows, and exported only passing text conversations.

**Result:** `product-a` passed 1/4 (0.25) and `product-b` passed 3/4 (0.75).
The exporter wrote four conversations and skipped four failed attempts.

---

### passed_only.py

**Status:** PASS

**Description:** Verified that the default exporter keeps passing attempts and
excludes failed attempts within selected learning-zone tasks.

**Result:** `product-a` passed 4/6 (0.67) and `product-d` passed 5/6 (0.83).
The JSONL contained exactly the nine passing attempts; three failed attempts
were excluded.

**Calibration:** The first task set (`product-a`, `product-c`, k=4) saturated at
4/4 on both rows. `product-c` was replaced with the harder `product-d` and k was
raised to six before this PASS was recorded.

---

### empty_zone_guard.py

**Status:** PASS

**Description:** Removed any stale artifact pair, exported the real learning-zone
selection, then exercised an explicit empty selection without calling the exporter.

**Result:** Final live run after adding stale-output cleanup: `easy-anchor` passed
4/4 (1.00), `product-a` passed 1/4 (0.25), and `product-b` passed 4/4 (1.00).
The real selection wrote one row; the synthetic empty selection was detected
and skipped. If a future real run has an empty zone, assertions verify that no
prior JSONL or sidecar remains at the advertised paths.

---
