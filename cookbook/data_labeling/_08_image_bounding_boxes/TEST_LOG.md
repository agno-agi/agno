# Test Log - _08_image_bounding_boxes

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Detects the main subject in a kayaker-in-whitewater photo (`www.gstatic.com/webp/gallery/2.jpg`) and returns one normalized bounding box via `output_schema=BoundingBox`. Exercises single-object detection with `[0, 1]` coordinates.

**Result:** Schema-valid box returned: `label='the main subject'`, `x=0.356`, `y=0.115`, `width=0.324`, `height=0.514` — a sensible tight box over the kayaker region. Note: the model echoes the prompt phrase as the label instead of a semantic label like "kayaker"; consistent across two runs. Coordinates vary slightly run to run (second run: `x=0.25`, `width=0.44`).

---

### multi_object.py

**Status:** PASS

**Description:** Detects multiple objects of multiple classes in a savanna scene (elephants, giraffes, zebras, crocodile) and returns a `Detection` with a list of labeled normalized boxes.

**Result:** 11 boxes returned: 6 `elephant`, 2 `giraffe`, 2 `zebra`, 1 `crocodile`. Coordinates are plausible and all in `[0, 1]` (e.g. crocodile at `x=0.606`, `y=0.848`, `width=0.321`, `height=0.081` along the bottom of the frame). Labels here are semantic, unlike the single-object files.

---

### with_confidence.py

**Status:** PASS

**Description:** Same kayaker photo as basic.py with a `confidence: Literal["high", "medium", "low"]` field added to the schema, so downstream consumers can threshold or route low-confidence boxes to review.

**Result:** Box returned with `confidence='high'`: `label='the main subject'`, `x=0.354`, `y=0.115`, `width=0.332`, `height=0.521` — nearly identical to the basic.py box, with the same prompt-echo label quirk.

---
