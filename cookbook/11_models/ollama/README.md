# Ollama Cookbook

> Note: Fork and clone this repository if needed

### 1. [Install](https://github.com/ollama/ollama?tab=readme-ov-file#macos) ollama and run models

Run your chat model

```shell
ollama pull llama3.1:8b
```

### 2. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 3. Export your `OLLAMA_API_KEY` if using Ollama Cloud

```shell
export OLLAMA_API_KEY=***
```

### 4. Install libraries

```shell
pip install -U ollama ddgs duckdb yfinance agno
```

### 5. Run basic Agent

- Streaming on

```shell
python cookbook/models/ollama/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/ollama/basic.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/ollama/tool_use.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/models/ollama/structured_output.py
```

### 8. Run Agent that uses storage

```shell
python cookbook/models/ollama/storage.py
```

### 9. Run Agent that uses knowledge

```shell
python cookbook/models/ollama/knowledge.py
```

### 10. Run Agent that uses memory

```shell
python cookbook/models/ollama/memory.py
```

### 11. Run Agent that interprets an image

Pull the llama3.2 vision model

```shell
ollama pull llama3.2-vision
```

```shell
python cookbook/models/ollama/image_agent.py
```

### 12. Run Agent that manually sets the Ollama client

```shell
python cookbook/models/ollama/set_client.py
```

### 13. See demos of some widely used models used via Ollama

```shell
python cookbook/models/ollama/demo_deepseek_r1.py
```

```shell
python cookbook/models/ollama/demo_qwen.py
```

```shell
python cookbook/models/ollama/demo_phi4.py
```
