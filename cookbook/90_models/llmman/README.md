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

The examples below use `qwen3:0.6b-q4_K_M` (0.6B parameters, ~0.4 GB), which runs on a laptop
without a dedicated GPU. Any reference `llmman pull` accepts works as a model id, including
HuggingFace references such as `hf.co/unsloth/Qwen3-0.6B-GGUF:Q4_K_M`.

```shell
llmman pull qwen3:0.6b-q4_K_M
llmman serve qwen3:0.6b-q4_K_M
```

`llmman serve` holds port 17434 until it is stopped, so a second `serve` fails with an address
in use error. Stop it with Ctrl+C in the serving terminal, or unload a single model with
`llmman stop <MODEL>`.

Set `LLMMAN_HOST` to bind elsewhere, then pass a matching `base_url`:

```python
Llmman(id="qwen3:0.6b-q4_K_M", base_url="http://192.168.1.10:17434/v1")
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
