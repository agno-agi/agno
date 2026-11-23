# Test Log - _12_trainer_loader

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Exported passing learning-zone attempts and loaded only their
message arrays, stopping before any training operation.

**Result:** `product-a` passed 3/6 (0.50) and `product-d` passed 6/6 (1.00).
The loader received three message arrays. No training was started or implied.

**Calibration:** The first task set (`product-a`, `product-b`, k=4) saturated at
4/4 on both rows. `product-b` was replaced with `product-d` and k was raised to
six before this PASS was recorded.

---

### validate_messages.py

**Status:** PASS

**Description:** Validated the portable SFT row keys, allowed roles, user and
final-assistant presence, and non-empty text content.

**Result:** `product-a` passed 1/4 (0.25) and `product-c` passed 4/4 (1.00).
The one exported passing row satisfied every loader-shape assertion. No training
was started.

---
