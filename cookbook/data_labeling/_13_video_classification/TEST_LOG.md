# Test Log - _13_video_classification

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Downloads `sample_seaview.mp4` from agno-public S3 and runs single-label closed-set classification (`scene_type` Literal with 7 options) via `output_schema` on Gemini with native video input.

**Result:** Returned `Classification(scene_type='indoor')`. Run took 9.8s (677 input / 10 output tokens, 313 reasoning). Note: despite the filename, the clip shows a scientist at a microscope in a lab, so `indoor` is correct.

---

### with_confidence.py

**Status:** PASS

**Description:** Same clip and label set, with an added `confidence` Literal field (`high`/`medium`/`low`) and instructions defining each confidence tier.

**Result:** Returned `Classification(scene_type='people', confidence='high')`. Run took 9.0s (724 input / 15 output tokens, 304 reasoning). Model picks a different valid label than basic.py — both `indoor` and `people` fit a person working in a lab.

---
