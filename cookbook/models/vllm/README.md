# vLLM Cookbook

vLLM is a fast and easy-to-use library for running LLM models locally.

## Setup

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install vLLM package

```shell
pip install vllm
```

### 3. Serve a model (this downloads the model to your local machine the first time you run it)

```shell
vllm serve Qwen/Qwen2.5-7B-Instruct \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --dtype float16 \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.9
```

## Examples

### 1. Basic Agent

```shell
python cookbook/models/vllm/basic.py
```
