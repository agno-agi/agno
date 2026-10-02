# VoicePipe implementation

## Open issues (deferred)

- [ ] `ElevenLabsTTS` plays no audio in a live call. Not yet investigated.
      Likely causes, unverified, most likely first:
      1. `output_format=pcm_24000` may need a paid plan; ElevenLabs lists raw PCM
         output under paid tiers, so a free key may be refused or sent another format.
      2. Errors in an undocumented shape go unnoticed: only an `error` field is
         checked, so another failure format waits silently until `response_timeout`.
      3. Audio is dropped if its `contextId` differs from the current reply's ID.
      Next step: read the server log from a silent call. A timeout or error points
      to 1 or 2; a clean log points to 3.
- [ ] `GeminiLiveSTT` does not work in a live call. Not yet investigated; no log captured.
      Possible causes, unverified, most likely first:
      1. Google never sends `setupComplete` (setup rejected, or the model is not
         available to the key), so connecting times out after `connect_timeout`.
      2. `audioStreamEnd` may end the whole audio stream rather than only the turn;
         the docs describe it as per-turn finalization, but if not, the first turn
         works and later ones get no transcript.
      3. Transcripts arrive under different field names than the documented
         `interimInputTranscription` and `inputTranscription`, so they are ignored.
      Next step: capture the server log from a failing call, and note whether the
      first turn transcribes.
- [ ] `GeminiTTS` lags and hits the free tier's 3 requests per minute (HTTP 429).
      Cause: Gemini TTS needs each request's full text, so the adapter sends one
      request per phrase, in order. Each phrase waits a full round trip, the first
      waits for the agent to finish that phrase, and a reply of three or more
      phrases uses the whole free-tier limit.
      Options: larger phrases, a paid tier, or a streaming-text TTS.
- [ ] Gemini examples lag overall. Besides the TTS cause above, two other stages
      can add delay, unmeasured:
      - `GeminiLiveSTT`: if no final transcript follows `audioStreamEnd`, the turn
        waits the full `finalize_timeout` (2 s) before using the text received so far.
      - LLM: a failed `gemini-3.5-flash-lite` request (a 503 took about 2.4 s) is
        paid before the `gemini-3.6-flash` fallback starts answering.
      Next step: compare the `transcript_final`, `first_token`, and
      `first_audio_sent` timings in the client to see which stage is slow.

- [x] `DeepgramSTT` (nova-3, any language code or `multi`), `SonioxSTT`
      (stt-rt-v5, automatic language detection), and `ElevenLabsTTS` (Flash v2.5 multi-context) over
      raw WebSockets, with `voice_providers.py` to switch between them.
- [x] `GeminiLiveSTT` (Live API transcription over WebSocket, hybrid VAD with
      `audioStreamEnd`) and `GeminiTTS` (Interactions API streaming, phrase by phrase).
- [ ] Verify Deepgram, Soniox, ElevenLabs, and Gemini with live keys across languages and
      accents; tune Deepgram `finalize_timeout` and `endpointing` from real timings.
- [x] Conversation history comes from the agent's session storage: history is on
      for voice runs, agents without a db get an in-memory db, and the turn after an
      interruption describes what was heard.
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
