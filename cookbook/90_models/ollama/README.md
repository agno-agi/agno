# Ollama Cookbook

> Note: Fork and clone this repository if needed

## Setup

### 1. Install Ollama

[Install Ollama](https://github.com/ollama/ollama?tab=readme-ov-file#macos) and pull a model:

```shell
ollama pull llama3.1:8b
```

### 2. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 3. Install libraries

```shell
pip install -U ollama agno
```

### 4. (Optional) Export your `OLLAMA_API_KEY` for Ollama Cloud

```shell
export OLLAMA_API_KEY=***
```

---

## Chat API Examples

The `chat/` folder contains examples using the native Ollama Chat API.

### Basic Usage

```shell
# Streaming
python cookbook/90_models/ollama/chat/basic_stream.py

# Non-streaming
python cookbook/90_models/ollama/chat/basic.py

# Async
python cookbook/90_models/ollama/chat/async_basic.py
```

### Tools and Structured Output

```shell
# Tool use
python cookbook/90_models/ollama/chat/tool_use.py

# Structured output
python cookbook/90_models/ollama/chat/structured_output.py
```

### Storage and Memory

```shell
# Database storage
python cookbook/90_models/ollama/chat/db.py

# Knowledge base
python cookbook/90_models/ollama/chat/knowledge.py

# Memory
python cookbook/90_models/ollama/chat/memory.py
```

### Vision

```shell
# Pull vision model first
ollama pull llama3.2-vision

python cookbook/90_models/ollama/chat/image_agent.py
```

### Model Demos

```shell
python cookbook/90_models/ollama/chat/demo_deepseek_r1.py
python cookbook/90_models/ollama/chat/demo_qwen.py
python cookbook/90_models/ollama/chat/demo_phi4.py
```

---

## Responses API Examples

The `responses/` folder contains examples using the OpenAI-compatible Responses API (requires Ollama v0.13.3+).

### Basic Usage

```shell
# Basic
python cookbook/90_models/ollama/responses/basic.py

# Streaming
python cookbook/90_models/ollama/responses/basic_stream.py

# Async
python cookbook/90_models/ollama/responses/async_basic.py
```

### Tools and Structured Output

```shell
# Tool use
python cookbook/90_models/ollama/responses/tool_use.py

# Structured output
python cookbook/90_models/ollama/responses/structured_output.py
```
