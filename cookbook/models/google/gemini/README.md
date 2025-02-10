# Google Gemini Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export `GOOGLE_API_KEY`

```shell
export GOOGLE_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U google-generativeai duckduckgo-search yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/google/gemini/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/google/gemini/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Agent

```shell
python cookbook/models/google/gemini/tool_use.py
```


### 6. Run Agent that returns structured output

```shell
python cookbook/models/google/gemini/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/google/gemini/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/google/gemini/knowledge.py
```

### 9. Run Agent that interprets an audio file

```shell
python cookbook/models/google/gemini/audio_agent.py
```

or

```shell
python cookbook/models/google/gemini/audio_agent_file_upload.py
```

### 10. Run Agent that analyzes an image

```shell
python cookbook/models/google/gemini/image_agent.py
```

or

```shell
python cookbook/models/google/gemini/image_agent_file_upload.py
```

### 11. Run Agent that analyzes a video

```shell
python cookbook/models/google/gemini/video_agent.py
```

### 12. Run Agent that uses flash thinking mode from Gemini

```shell
python cookbook/models/google/gemini/flash_thinking_agent.py
```
