# ElevenLabs TTS Test Log

## 2026-10-02

### Live call

**Status:** FAIL

**Description:** Ran an example with real keys and spoke to it.

**Result:** No audio was played back. Not yet investigated; tracked in
`cookbook/05_agent_os/28_voice_pipe/implementation.md`.

---

### All examples

**Status:** PASS for offline checks; NOT RUN against the live provider

**Description:** Loaded each example without starting the server to confirm the
agent, voice pipe, and AgentOS app build and that `/voice/voice/ws` is registered.
No API keys were read and no provider connections were opened.

**Result:** Configuration loads. Live speech quality and latency are not yet measured.

---
