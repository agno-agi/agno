# Meta Llama API Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `LLAMA_API_KEY`

```shell
export LLAMA_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U agno llama-api-client
```

If using LlamaOpenAI, install the following:

```shell
uv pip install -U agno openai
```

### 4. Run a basic Agent

```shell
python cookbook/90_models/meta/llama/basic.py
```

### 5. Run an Agent with Tools

> Run `uv pip install ddgs` to install dependencies.

```shell
python cookbook/90_models/meta/llama/tool_use.py
```
