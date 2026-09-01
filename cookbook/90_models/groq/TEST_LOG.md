# TEST_LOG

Tested 2026-09-01 with a live `GROQ_API_KEY`, agno @ main (1b7800746). Only the
file below has been run; no other cookbook in this directory has a recorded
result yet.

### image_agent.py

**Status:** PASS (streaming caveat disclosed)

**Description:** Sends an image by URL to `qwen/qwen3.6-27b` and asks for a
description. The image is the public `agno-public` S3 photo of Krakow's Main
Market Square (the previous Wikimedia URL returned 403 to Groq's server-side
fetch — Wikimedia blocks non-browser user agents).

**Result:** Groq fetched the S3 URL and the model returned a genuine, accurate
description of the image in both runs. Caveat: with `stream=True` (as the file
is written) the streamed output contains the model's raw `<think>` reasoning
and the stream ended before the final answer in both runs; a non-streaming run
of the identical agent completed with the full description after the reasoning
block. This is a qwen-reasoning-tokens / streaming interaction, unrelated to
the URL change.

---
