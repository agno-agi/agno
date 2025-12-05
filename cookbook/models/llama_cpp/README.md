# Llama CPP Cookbook

> Note: Fork and clone this repository if needed

### 1. [Install](https://github.com/ggerganov/llama.cpp) Llama CPP and download a model

Run your chat model using Llama CPP. For the examples below make sure to download `ggml-org/gpt-oss-20b-GGUF`. Please also make sure that the model is reachable at `http://127.0.0.1:8080/v1`.

Command to run GPT-OSS-20B:

```shell
llama-server -hf ggml-org/gpt-oss-20b-GGUF  --ctx-size 0 --jinja -ub 2048 -b 2048
```

### 2. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 3. Install libraries

```shell
pip install -U ddgs openai agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/llama_cpp/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/llama_cpp/basic.py
```

### 5. Run Agent with Tools

- Streaming on

```shell
python cookbook/models/llama_cpp/tool_use_stream.py
```

- Streaming off

```shell
python cookbook/models/llama_cpp/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/llama_cpp/structured_output.py
```
