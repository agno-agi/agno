# Deepgram STT

[Provider documentation](https://developers.deepgram.com/docs/models-languages-overview)

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
export DEEPGRAM_API_KEY=xxx
```

### 3. Install libraries

```shell
uv pip install -U "agno[voice]"
```

### 4. Run an example

```shell
python cookbook/14_voice/stt/deepgram/basic.py
```

Then open the voice client from `cookbook/05_agent_os/28_voice_pipe/client` at
<http://localhost:3000/?pipe=voice>, or choose Voice mode in Agent UI.

| Example | What it shows |
| --- | --- |
| `basic.py` | Live transcripts with `nova-3`. |
| `language.py` | Any supported language or regional variant, set with `VOICE_LANGUAGE`. |
| `multilingual.py` | Speakers who switch languages, with `language="multi"`. |
| `keyterms.py` | Boosted recognition of product names and jargon. |
