# Test Log - _06_image_classification

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Single-label scene-type classification with a Literal output schema (wildlife / landscape / sports / architecture / other) over four image URLs: a Google generative-AI wildlife sample, two gstatic webp gallery photos, and the agno-public Krakow basilica photo.

**Result:** All four images classified as expected: elephants/giraffes/zebras sunset -> `wildlife`, gstatic gallery/1.jpg -> `landscape`, gstatic gallery/2.jpg -> `sports`, krakow_mariacki.jpg -> `architecture`. Each run returned a validated `Classification` object; per-image latency 1.2-3.2s.

---

### multilabel.py

**Status:** PASS

**Description:** Multi-label scene tagging with a List[Literal] output schema over eight possible tags (outdoor, indoor, daytime, nighttime, people, vehicle, nature, architecture) on the Krakow basilica photo and the Google generative-AI wildlife sample.

**Result:** krakow_mariacki.jpg -> `['outdoor', 'nighttime', 'architecture']`; elephants/giraffes/zebras sunset -> `['outdoor', 'daytime', 'nature']`. Both tag sets coherent with image content; each run returned a validated `Tagging` object; per-image latency 2.8-5.6s.

---
