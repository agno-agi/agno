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
pip install -U agno llama-api-client
```

If using LlamaOpenAI, install the following:

```shell
pip install -U agno openai
```

### 4. Run a basic Agent

- Streaming on

```shell
python cookbook/models/meta/llama/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/meta/llama/basic.py
```

### 5. Run an Agent with Tools

> Run `pip install ddgs` to install dependencies.

- Streaming on

```shell
python cookbook/models/meta/llama/tool_use_stream.py
```

- Streaming off

```shell
python cookbook/models/meta/llama/tool_use.py
```
