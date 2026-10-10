# Voice Providers

Speech-to-text and text-to-speech providers for `VoicePipe`, which gives an Agno
agent a live voice through AgentOS. For the full voice walkthrough, the browser
client, and the wire protocol, see
[`05_agent_os/28_voice_pipe`](../05_agent_os/28_voice_pipe).

## Providers

| Kind | Provider | Key | Examples |
|:-----|:---------|:----|:---------|
| STT | [OpenAI Realtime STT](./stt/openai) | `OPENAI_API_KEY` | 2 |
| STT | [Deepgram STT](./stt/deepgram) | `DEEPGRAM_API_KEY` | 4 |
| STT | [Soniox STT](./stt/soniox) | `SONIOX_API_KEY` | 3 |
| STT | [Gemini Live STT](./stt/gemini) | `GOOGLE_API_KEY` | 2 |
| TTS | [OpenAI TTS](./tts/openai) | `OPENAI_API_KEY` | 1 |
| TTS | [Cartesia TTS](./tts/cartesia) | `CARTESIA_API_KEY` | 2 |
| TTS | [ElevenLabs TTS](./tts/elevenlabs) | `ELEVEN_LABS_API_KEY` | 2 |
| TTS | [Gemini TTS](./tts/gemini) | `GOOGLE_API_KEY` | 2 |

Apart from the Gemini examples, which run the agent on Gemini, every example uses
`OPENAI_API_KEY` for the agent's model. Speech-to-text examples speak their replies
with Cartesia (`CARTESIA_API_KEY`); text-to-speech examples listen with OpenAI.

## Getting started

```shell
uv pip install -U "agno[voice]"
export OPENAI_API_KEY=xxx
export DEEPGRAM_API_KEY=xxx
export CARTESIA_API_KEY=xxx
python cookbook/14_voice/stt/deepgram/basic.py
```

Every example serves the same voice pipe ID on port 7777, so one client URL works
for all of them: run the client from `cookbook/05_agent_os/28_voice_pipe/client`
and open <http://localhost:3000/?pipe=voice>, or choose Voice mode in Agent UI.
Stop one example before starting the next.

## Languages

Each provider supports many languages; see its documentation for the current list.

- `stt/deepgram/language.py` and the `language_hints.py` examples for OpenAI,
  Soniox, and Gemini read the language codes your users speak from
  `VOICE_LANGUAGE` or `VOICE_LANGUAGES`.
- `stt/deepgram/multilingual.py`, `stt/soniox/basic.py`, and `stt/gemini/basic.py`
  recognize speakers who switch languages, even mid-sentence.

Recognition quality varies by language, accent, and audio, so try your users'
own speech with each provider.

## Pairing providers

Any recognizer works with any voice. Swap the `stt_model` or `tts_model` on the
`VoicePipe` in an example, for example `DeepgramSTT(language="multi")` with
`ElevenLabsTTS()`.
