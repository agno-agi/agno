# Gemini TTS Test Log

## 2026-10-02

### Live call

**Status:** FAIL

**Description:** Ran an example with real keys on the Gemini free tier.

**Result:** Replies lagged, then failed with HTTP 429: the free tier allows 3
requests per minute for `gemini-3.8-flash-lite-tts`, and one request is sent per
phrase. Not yet addressed; tracked in
`cookbook/05_agent_os/28_voice_pipe/implementation.md`.

---

### All examples

**Status:** PASS for offline checks; NOT RUN against the live provider

**Description:** Loaded each example without starting the server to confirm the
agent, voice pipe, and AgentOS app build and that `/voice/voice/pipe` is registered.
No API keys were read and no provider connections were opened.

**Result:** Configuration loads. Live speech quality and latency are not yet measured.

---
