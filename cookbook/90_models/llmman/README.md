# Llmman Cookbook

> Note: Fork and clone this repository if needed

[llmman](https://github.com/llmmanorg/llmman) runs local models distributed as OCI
artifacts and serves an OpenAI-compatible API on `http://127.0.0.1:17434/v1`. No API
key is needed.

### 1. Install llmman

Linux, macOS:

```shell
curl -fsSL https://raw.githubusercontent.com/llmmanorg/llmman/main/install.sh | sh
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/llmmanorg/llmman/main/install.ps1 | iex
```

### 2. Pull a model and start the server

The examples below use `gemma4`. Any reference `llmman pull` accepts works as a model id,
including tags such as `qwen3.5:0.8B`.

```shell
llmman pull gemma4
llmman serve
```

Set `LLMMAN_HOST` to bind elsewhere, then pass a matching `base_url`:

```python
Llmman(id="gemma4", base_url="http://192.168.1.10:17434/v1")
```

### 3. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 4. Install libraries

```shell
uv pip install -U ddgs openai agno
```

### 5. Run basic Agent

```shell
python cookbook/90_models/llmman/basic.py
```

### 6. Run Agent with Tools

```shell
python cookbook/90_models/llmman/tool_use.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/90_models/llmman/structured_output.py
```

### 8. Run Agent that retries failed requests

```shell
python cookbook/90_models/llmman/retry.py
```
