# Test Log -- 12_multimodal

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### audio_input_output.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audio input output. Ran successfully and produced expected output.
**Result:** Completed successfully in 7s.

---

### audio_sentiment_analysis.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audio sentiment analysis. Ran successfully and produced expected output.
**Result:** Completed successfully in 20s.

---

### audio_streaming.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audio streaming. Ran successfully and produced expected output.
**Result:** Completed successfully in 6s.

---

### audio_to_text.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates audio to text. Ran successfully and produced expected output.
**Result:** Completed successfully in 9s.

---

### image_to_audio.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates image to audio. Ran successfully and produced expected output.
**Result:** Completed successfully in 17s.

---

### image_to_image.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates image to image. Failed due to missing dependency: ModuleNotFoundError: No module named 'fal_client'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---

### image_to_structured_output.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates image to structured output. Ran successfully and produced expected output.
**Result:** Completed successfully in 1s.

---

### image_to_text.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates image to text. Ran successfully and produced expected output.
**Result:** Completed successfully in 3s.

---

### media_input_for_tool.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates media input for tool. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### video_caption.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates video caption. Failed due to missing dependency: ModuleNotFoundError: No module named 'moviepy'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---
