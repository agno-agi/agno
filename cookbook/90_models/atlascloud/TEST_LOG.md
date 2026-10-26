# Atlas Cloud Cookbook Tests

## basic.py

**Status:** PASS

**Description:** Executed the default synchronous example against Atlas Cloud on
2026-09-17 with `deepseek-ai/deepseek-v3.2`, SDK retries disabled and telemetry off.

**Result:** One request returned a non-empty, one-sentence explanation of an AI
agent; process exited with status 0. Reported response time was 3.6 seconds.
No repeat paid request was made. Async and provider-string construction are
covered by unit tests, not additional live requests.
