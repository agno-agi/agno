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

```shell
python cookbook/90_models/litellm/basic.py
```

### 5. Run Agent with Tools

- Financial data

```shell
python cookbook/90_models/litellm/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/litellm/structured_output.py
```

### 7. Run Agent that uses memory

```shell
python cookbook/90_models/litellm/memory.py
```

### 8. Run Agent that uses storage

```shell
python cookbook/90_models/litellm/db.py
```

### 9. Run Agent that uses knowledge

```shell
python cookbook/90_models/litellm/knowledge.py
```

### 10. Run Agent that analyzes images

- URL-based image

```shell
python cookbook/90_models/litellm/image_agent.py
```

- Byte-based image

```shell
python cookbook/90_models/litellm/image_agent_bytes.py
```

### 11. Run Agent that analyzes audio

```shell
python cookbook/90_models/litellm/audio_input_agent.py
```

### 12. Run Agent that processes PDF files

- Local PDF file

```shell
python cookbook/90_models/litellm/pdf_input_local.py
```

- Remote PDF URL

```shell
python cookbook/90_models/litellm/pdf_input_url.py
```

- PDF from bytes

```shell
python cookbook/90_models/litellm/pdf_input_bytes.py
```

### 13. Run Agent with metrics

```shell
python cookbook/90_models/litellm/metrics.py
```
