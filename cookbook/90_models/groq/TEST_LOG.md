# TEST_LOG

Tested 2026-09-01 with a live `GROQ_API_KEY`, agno @ main (1b7800746). Only the
file below has been run; no other cookbook in this directory has a recorded
result yet.

### image_agent.py

**Status:** PASS

**Description:** Sends an image by URL to `qwen/qwen3.6-27b` (with
`reasoning_effort="none"`) and streams a description. The image is the public
`agno-public` S3 photo of Krakow's Main Market Square (the previous Wikimedia
URL returned 403 to Groq's server-side fetch — Wikimedia blocks non-browser
user agents).

**Result:** Two streamed runs completed cleanly with genuine, accurate
descriptions of the image. `reasoning_effort="none"` matters: with qwen's
default thinking enabled, the raw `<think>` tokens stream into the response
and the run can end before the answer appears (observed in 2 of 2 streamed
and 2 of 3 non-streamed runs without the flag). The flag disables thinking so
the streamed answer is immediate and complete; verified 4 of 4 with it (two
raw API calls, two full cookbook runs).

---
