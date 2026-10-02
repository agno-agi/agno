# ElevenLabs TTS

[Provider documentation](https://elevenlabs.io/docs/overview/models)

Each example listens with `OpenAIRealtimeSTT`, so only one extra key is needed.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Set your API keys

```shell
export OPENAI_API_KEY=xxx
export ELEVEN_LABS_API_KEY=xxx
# Optional; defaults to the same voice as ElevenLabsTools.
export ELEVEN_LABS_VOICE_ID=xxx
```

### 3. Install libraries

```shell
uv pip install -U "agno[voice]"
```

### 4. Run an example

```shell
python cookbook/14_voice/tts/elevenlabs/basic.py
```

Then open the voice client from `cookbook/05_agent_os/28_voice_pipe/client` at
<http://localhost:3000/?pipe=voice>, or choose Voice mode in Agent UI.

| Example | What it shows |
| --- | --- |
| `basic.py` | Streaming speech with `eleven_flash_v2_5`. |
| `voice_settings.py` | Tuned stability, similarity, speed, and chunk sizes. |
