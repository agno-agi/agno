# Huggingface Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export `HUGGINGFACE_API_KEY`

```shell
export HUGGINGFACE_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U huggingface_hub agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/huggingface/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/huggingface/basic.py
```

### 5. Run agent with tools

- An essay writer using Llama model

```shell
python cookbook/models/huggingface/llama_essay_writer.py
```
