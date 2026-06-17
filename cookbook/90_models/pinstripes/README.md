# Pinstripes

Cookbook examples for `cookbook/90_models/pinstripes`.

[Pinstripes](https://pinstripes.io) is an OpenAI-compatible LLM inference API offering low-cost access to state-of-the-art open-weight models.

## Available Models

| Model ID | Name | Price |
|---|---|---|
| `ps/deepseek-v4-flash` | DeepSeek V4 Flash | $0.10/M tokens |
| `ps/glm-4.5-air` | GLM-4.5-Air | $0.125/M tokens |
| `ps/qwen3-35b` | Qwen3-35B | $0.14/M tokens |
| `ps/minimax-m2.7` | MiniMax M2.7 | $0.255/M tokens |

## Setup

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `PINSTRIPES_API_KEY`

Get your API key at https://pinstripes.io.

```shell
export PINSTRIPES_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

## Run Examples

### Basic Agent

```shell
python cookbook/90_models/pinstripes/basic.py
```

### Agent with Tool Use

```shell
python cookbook/90_models/pinstripes/tool_use.py
```

### Agent with Structured Output

```shell
python cookbook/90_models/pinstripes/structured_output.py
```
