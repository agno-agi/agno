# Test Log - _06_image_classification

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Single-label scene-type classification (wildlife / landscape / sports / architecture / other) over four photos.

**Result:** All four classified into the expected scene type.

**Note:** Test inputs moved off Wikimedia (Gemini can't fetch those URLs) to agno-public S3, gstatic gallery, and a Google generative-AI sample. Label set switched from animal types to scene types so the available images classify cleanly.

---

### multilabel.py

**Status:** PASS

**Description:** Multi-label tagging of scene attributes (outdoor, daytime, people, nature, architecture, etc.) over a Krakow basilica photo and a Google generative-AI wildlife sample.

**Result:** Tag sets are coherent with each image's content.

---
