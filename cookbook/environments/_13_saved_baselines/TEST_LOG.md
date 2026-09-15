# Test Log - _13_saved_baselines

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Saved a live twelve-attempt result as a plain JSON baseline.

**Result:** `product-a` passed 3/6 (0.50) and `product-d` passed 3/6 (0.50).
All twelve attempts were written to the generated baseline artifact.

**Calibration:** The first task set (`product-a`, `product-b`, k=4) saturated at
4/4 on both rows. `product-b` was replaced with `product-d` and k was raised to
six before this PASS was recorded.

---

### reload_baseline.py

**Status:** PASS

**Description:** Saved and reloaded a baseline, then compared its complete
`summary()` result with the live object.

**Result:** `product-a` passed 2/4 (0.50) and `product-c` passed 4/4 (1.00).
The aggregate pass rate was 0.75 and both fingerprints survived the round trip.

---

### async_save_load.py

**Status:** PASS

**Description:** Used `arun_rollouts`, `asave`, and `aload` inside one event loop.

**Result:** `product-a` passed 3/4 (0.75) and `product-b` passed 4/4 (1.00).
The async round trip preserved all eight attempts and the complete summary.

---
