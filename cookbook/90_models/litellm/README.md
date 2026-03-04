# LiteLLM Cookbooks

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your API keys
Regardless of the model used—OpenAI, Hugging Face, or XAI—the API key is referenced as `LITELLM_API_KEY`.

```shell
export LITELLM_API_KEY=***
```

You can also reference the API key depending on the model you will use, e.g. `OPENAI_API_KEY` if you will use an OpenAI model like GPT-4o.

```shell
export OPENAI_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U litellm ddgs duckdb yfinance agno
```

### 4. Run an Agent

- Streaming off

```shell
python cookbook/92_models/litellm/basic.py
```

- Streaming on

```shell
python cookbook/92_models/litellm/basic_stream.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/92_models/litellm/tool_use.py
```

- Tool use with streaming

```shell
python cookbook/92_models/litellm/tool_use_stream.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/92_models/litellm/structured_output.py
```

### 7. Run Agent that uses memory

```shell
python cookbook/92_models/litellm/memory.py
```

### 8. Run Agent that uses storage

```shell
python cookbook/92_models/litellm/storage.py
```

### 9. Run Agent that uses knowledge

```shell
python cookbook/92_models/litellm/knowledge.py
```

### 10. Run Agent that analyzes images

- URL-based image

```shell
python cookbook/92_models/litellm/image_agent.py
```

- Byte-based image

```shell
python cookbook/92_models/litellm/image_agent_bytes.py
```

### 11. Run Agent that analyzes audio

```shell
python cookbook/92_models/litellm/audio_input_agent.py
```

### 12. Run Agent that processes PDF files

- Local PDF file

```shell
python cookbook/92_models/litellm/pdf_input_local.py
```

- Remote PDF URL

```shell
python cookbook/92_models/litellm/pdf_input_url.py
```

- PDF from bytes

```shell
python cookbook/92_models/litellm/pdf_input_bytes.py
```

### 13. Run Agent with metrics

```shell
python cookbook/92_models/litellm/metrics.py
```

### 14. Run async Agents

- Basic async

```shell
python cookbook/92_models/litellm/async_basic.py
```

- Async with streaming

```shell
python cookbook/92_models/litellm/async_basic_stream.py
```

- Async with tools

```shell
python cookbook/92_models/litellm/async_tool_use.py
```
