# Test Log - _08_image_bounding_boxes

Tested 2026-05-17 against `gpt-5.5` (OpenAIResponses), agno 2.6.6.

### basic.py

**Status:** PASS

**Description:** Detect the main subject in a cat photo, return one normalized bounding box.

**Result:** Sensible tight box around the cat (x=0.22, y=0.12, w=0.69, h=0.86).

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with a `confidence` field added to the schema.

**Result:** Returns sensible box (x=0.215, y=0.115, w=0.69, h=0.84) with `high` confidence.

**Note:** Initially produced degenerate boxes (all-zero or all-one). Fix: added per-field descriptions on x/y/w/h and expanded coordinate guidance in the instructions to match `basic.py`. Without that grounding, `gpt-5.5` does not consistently produce sensible coordinates.

---

### multi_object.py

**Status:** PASS

**Description:** Detect multiple objects in an image, return a list of bounding boxes.

**Result:** Multiple boxes returned with reasonable coordinates and labels.

---
