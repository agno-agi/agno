# Test Log - _10_audio_classification

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Downloads an mp3 clip (QA-01.mp3 from the agno-public S3 bucket) and asks a Gemini agent with an `output_schema` to assign a single language label from a closed Literal set (english, spanish, french, german, mandarin, hindi, other).

**Result:** Returned `Classification(language='english')`. Single model call, 1921 input / 6 output tokens, 2.36s.

---

### with_confidence.py

**Status:** PASS

**Description:** Same language-identification task on the same clip, with the schema extended by a `confidence` Literal field (high, medium, low) and instructions defining each confidence tier for downstream routing.

**Result:** Returned `Classification(language='english', confidence='high')`. Single model call, 1965 input / 12 output tokens, 1.67s.

---
