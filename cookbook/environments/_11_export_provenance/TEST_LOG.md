# Test Log - _11_export_provenance

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
