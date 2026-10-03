# OpenAI Realtime STT

[Provider documentation](https://platform.openai.com/docs/guides/speech-to-text)

Each example speaks its replies with `CartesiaTTS`, which streams speech as the agent writes, so it also needs `CARTESIA_API_KEY`.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Set your API keys

```shell
export OPENAI_API_KEY=xxx
export CARTESIA_API_KEY=xxx
```

### 3. Install libraries

```shell
uv pip install -U "agno[voice]"
```

### 4. Run an example

```shell
python cookbook/14_voice/stt/openai/basic.py
```

Then open the voice client from `cookbook/05_agent_os/28_voice_pipe/client` at
<http://localhost:3000/?pipe=voice>, or choose Voice mode in Agent UI.

| Example | What it shows |
| --- | --- |
| `basic.py` | Live transcripts with `gpt-live-transcribe`. |
| `language_hints.py` | Hints for expected languages, set with `VOICE_LANGUAGES`, and boosted keywords. |
