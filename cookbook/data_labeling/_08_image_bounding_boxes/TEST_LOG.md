# Test Log - _08_image_bounding_boxes

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### basic.py

**Status:** PASS

**Description:** Detect the main subject in a kayaker-in-whitewater photo, return one normalized bounding box.

**Result:** Sensible tight box around the kayaker.

**Note:** Test image switched from a Wikimedia cat photo (Gemini can't fetch those URLs) to `www.gstatic.com/webp/gallery/2.jpg`.

---

### multi_object.py

**Status:** PASS

**Description:** Detect multiple objects in an image, return a list of bounding boxes. Input is a savanna scene with elephants, giraffes, zebras, and a crocodile.

**Result:** Multiple boxes returned with reasonable coordinates and per-animal labels.

**Note:** Test image switched from a Wikimedia "Collage of Nine Dogs" (Gemini can't fetch those URLs) to a Google generative-AI sample at `storage.googleapis.com/generativeai-downloads/images/generated_elephants_giraffes_zebras_sunset.jpg`.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with a `confidence` field added to the schema (kayaker-in-whitewater photo).

**Result:** Sensible bounding box around the kayaker with `high` confidence.

**Note:** Per-field `description` on `x`, `y`, `width`, `height` is load-bearing — without it, and without the `[0, 1]` coordinate convention spelled out in instructions, models tend to return degenerate boxes (all-zero or whole-image).

---
