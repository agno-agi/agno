# VoicePipe implementation

- [x] AgentOS adds only the canonical WebSocket route `/voice/{id}/pipe` per live
      socket; the browser client lives in the cookbook, and INTEGRATION.md documents
      the protocol for custom clients.
- [x] `GET /voice` lists each pipe with its agent ID, name, and WebSocket path,
      filtered by agent read access and shown in `/docs`.
- [x] Browser voice interface with responsive layout, transcript, mic selection,
      mute/end controls, authentication input, and explicit errors.
- [x] Redesign with Agent UI's charcoal/orange design tokens, compact sidebar,
      and connecting/thinking spinners with reduced-motion support.
- [x] AudioWorklet capture with fixed PCM16 frames and a continuous resampling clock.
- [x] Streaming playback with reply IDs, stale-audio rejection, and device-clock
      playback acknowledgments before interruption cleanup.
- [x] Pace server audio to a two-second playback window; keep the browser queue
      bounded by actual samples and handle stale browser output timestamps.
- [x] Regression checks for a fast 40-second speech burst, interruptions while
      waiting for playback, missing acknowledgments, and stale output clocks.
- [x] Expandable timing panel that distinguishes server send time from estimated
      audible playback and explains the endpointing window.
- [x] AgentOS cookbook wrapping an existing Agno agent with explicit English STT
      and response instructions.
- [x] Standalone tools example with Agno's CalculatorTools and WebSearchTools.
- [x] Standalone Agno docs example loading docs.agno.com/llms.txt into local
      LanceDB with OpenAI embeddings and Agno's knowledge search tool.
- [x] Document provider setup, an OpenAI TTS alternative, and current limitations.
- [x] Verify an OpenAI-only live provider run using synthetic English input and
      record stage timings in `TEST_LOG.md`; 4,660 ms to first audio did not meet
      the sub-second response target.
- [ ] Verify the default Cartesia provider with credentials and a real microphone
      conversation; record repeated latency and audio-quality observations.
- [ ] Compare repeated measurements against a matched Pipecat or LiveKit setup.

WebRTC, semantic turn detection, and a background thinker are future work.
