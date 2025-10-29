# OpenAI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `OPENAI_API_KEY`

```shell
export OPENAI_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/openai/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/openai/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/openai/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/openai/structured_output.py
```

### 7. Run Agent uses memory

```shell
python cookbook/models/openai/memory.py
```

### 8. Run Agent that uses storage

```shell
python cookbook/models/openai/storage.py
```

### 9. Run Agent that uses knowledge

```shell
python cookbook/models/openai/knowledge.py
```

### 10. Run Agent that generates an image using Dall-E

```shell
python cookbook/models/openai/generate_images.py
```

### 11. Run Agent that analyzes an image

```shell
python cookbook/models/openai/image_agent.py
```

or

```shell
python cookbook/models/openai/image_agent_with_memory.py
```

### 11. Run Agent that analyzes audio

```shell
python cookbook/models/openai/audio_input_agent.py
```

### 12. Run Agent that generates audio

```shell
python cookbook/models/openai/audio_output_agent.py
```
