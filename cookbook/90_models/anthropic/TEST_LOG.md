# TEST_LOG

### prompt_caching_prewarm.py

**Status:** PASS

**Description:** Runs Anthropic cache pre-warming — `Claude.prewarm()` fires a `max_tokens=0` request to load the system prompt into the cache, then an `agent.run()` reads from the warm cache.

**Result:** Ran end to end with no errors. Output: `Pre-warm cache write tokens = 3938`, `First run cache read tokens = 3938`. The pre-warm wrote 3,938 tokens into the cache, and the first real agent run then read all 3,938 from the warm cache — confirming the pre-warm primed the cache and the follow-up request hit it.

---
