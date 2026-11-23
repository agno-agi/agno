# Test Log - _24_structured_extraction

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Typed operative-account extraction with amendments at K=4.

**Result:** `partial-amendment` 4/4, `rejected-revision` 4/4,
`later-narrow-amendment` 2/4, `contingent-rescission` 4/4, and
`as-of-effective-date` 4/4. Value-only extraction saturated at 4/4 across the
first three rows, then across all five rows. Exact operative-source provenance
exposed the 2/4 middle band.

---

### conflicting_fields.py

**Status:** PASS

**Description:** Per-field shipment precedence, discarded-source provenance,
and an evidence-derived audit checksum at K=6.

**Result:** Final live run after correcting the signed-correction gold answer:
`scan-and-correction` 2/6, `voided-later-scan` 4/6,
`narrow-latest-correction` 0/6, and `timestamped-source-audit` 3/6. Three rows
landed in the true partial pass-rate band; the 0/6 row remains visible as a
no-signal failure boundary.

**Calibration:** The earlier `voided-later-scan` gold incorrectly allowed a
lower-precedence scan to override a signed correction and was discarded. After
that fix, field values, exact source ids, discarded-source lists, a 12-source
timestamped audit, and a short weighted checksum all saturated. The final
discarded-evidence checksum derives a seed from the source ids and runs eight
modular recurrence rounds, escaping the 6/6 wall in 98 seconds.

---

### nested_records.py

**Status:** PASS

**Description:** Nested amended order and shipment extraction at K=4.

**Result:** Final live run after removing audit ids for events that no longer
changed the normalized snapshot: `amended-split-shipment` 2/4,
`voided-and-repacked` 2/4, `partial-allocation-repack` 4/4, and
`multi-stage-fulfillment` 4/4. SKU-only, quantity-aware, and audit-trail-only
versions each saturated at 4/4. The corrected event contract plus unshipped-item
reconciliation retained two genuine 2/4 learning-zone rows.

---
