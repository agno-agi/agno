# Test Log - _11_export_provenance

## Re-test 2026-07-20 — fix/cookbooks-claude (Agno 2.8.0 source)

### basic.py — FIXED

**Fix:** both tasks saturated at k=4, so `learning_zone()` was empty and the file
printed its guard ("No learning-zone tasks; make the tasks harder") instead of
exporting — the provenance sidecar it exists to show never appeared. `product-b`
replaced with a second independent calibrated chain (expected 10481347) so a zone
row is reliable and the export runs.

**Grid (k=4):** `product-a` 3/4 (0.75, zone); `product-b` 4/4. Exported 3 dataset
rows and 3 sidecar rows with env/policy fingerprints.

`inspect_sidecar.py` (a=0.50, zone) re-ran clean and unchanged.

---

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Exported a verified dataset and loaded the generated provenance
sidecar.

**Result:** `product-a` passed 3/4 (0.75) and `product-b` passed 4/4 (1.00).
The dataset and sidecar each contained three entries, with both fingerprints
present in the sidecar.

---

### inspect_sidecar.py

**Status:** PASS

**Description:** Validated sidecar fingerprints and passing-attempt references,
then joined trusted exported rows to task ids, zero-based attempt indexes, and
scores.

**Result:** Final live run after adding stale-pair cleanup and non-null fingerprint
guards: `product-a` passed 3/6 (0.50) and `product-d` passed 6/6 (1.00).
Three exported rows aligned one-to-one with valid passing attempts and matching
fingerprints. The example also printed that the sidecar records provenance but
does not authenticate the JSONL because it carries no dataset digest.

**Calibration:** The first post-guard rerun saturated at 4/4 on both `product-a`
and `product-c`. That grid was rejected; `product-c` was replaced by the harder
`product-d` boundary and K was raised to six before this PASS was recorded.

---
