# Test Log: 17_fallback_models

### 05_sticky_fallback.py

**Status:** PASS

**Description:** Primary `OpenAIResponses` points at an unreachable server; `FallbackConfig(sticky=True, retry_primary_after=300)` with a Claude fallback. Run 1 fails on the primary, falls back to Claude and fires the callback. `get_sticky_fallback(agent.model)` then reports the Claude model. Run 2 goes straight to Claude: no primary connection error, no fallback warning, no callback.

**Result:** Both runs answered by the fallback; the primary was attempted only once.

---
