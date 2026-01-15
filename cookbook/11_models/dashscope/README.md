# DashScope Cookbook

Qwen model integration with Agno framework. Supports cloud deployment via DashScope API and local deployment via LM Studio, Ollama, or vLLM.

## Cloud Deployment

### Setup

```shell
# Create virtual environment
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate

# Install dependencies
pip install -U openai ddgs agno

# Set API key (get from https://modelstudio.console.alibabacloud.com)
export DASHSCOPE_API_KEY=***
```

### Examples

```shell
# Basic
python cookbook/models/dashscope/basic.py
python cookbook/models/dashscope/basic_stream.py

# Async
python cookbook/models/dashscope/async_basic.py
python cookbook/models/dashscope/async_basic_stream.py

# Tools
python cookbook/models/dashscope/tool_use.py
python cookbook/models/dashscope/async_tool_use.py

# Structured output
python cookbook/models/dashscope/structured_output.py

# Image analysis
python cookbook/models/dashscope/image_agent.py
python cookbook/models/dashscope/image_agent_bytes.py
python cookbook/models/dashscope/async_image_agent.py

# Multi-turn conversations
python cookbook/models/dashscope/multi_turn_conversation.py

# Code generation
python cookbook/models/dashscope/code_generation.py

# Long context
python cookbook/models/dashscope/long_context.py

# Batch processing
python cookbook/models/dashscope/batch_processing.py
```

## Local Deployment

### Quick Start - LM Studio

1. **Download LM Studio:** https://lmstudio.ai/

2. **Download Models** (search in LM Studio, download Q4_K_M):
   - `qwen2.5-3b-instruct` - General purpose
   - `Qwen2.5-Coder-3B-Instruct` - Code generation
   - `Qwen3-VL-2B-Instruct` - Vision + reasoning (lighter)

3. **Start Server:** Local Server → Load model → Start (port 1234)

4. **Run Examples:**

```bash
# Basic
python cookbook/models/dashscope/qwen_local.py

# Advanced
python cookbook/models/dashscope/qwen_parallel_tools.py          # Parallel function calls
python cookbook/models/dashscope/qwen_reasoning_content.py       # Reasoning process
python cookbook/models/dashscope/multi_turn_conversation.py      # Conversations with memory
python cookbook/models/dashscope/code_generation.py              # Code generation
python cookbook/models/dashscope/long_context.py                 # Long context (32K+)
python cookbook/models/dashscope/batch_processing.py             # Batch processing
python cookbook/models/dashscope/image_agent.py                  # Image analysis
```

### Model Configuration

```python
# General purpose
MODEL_ID = "qwen2.5-3b-instruct"
BASE_URL = "http://localhost:1234/v1"

# Code generation
MODEL_ID = "qwen2.5-coder-3b-instruct"
BASE_URL = "http://localhost:1234/v1"

# Vision + reasoning
MODEL_ID = "qwen3-vl-2b-instruct"
BASE_URL = "http://localhost:1234/v1"
```

### Provider Configuration

**LM Studio:**
```python
BASE_URL = "http://localhost:1234/v1"
```

**Ollama:**
```python
MODEL_ID = "qwen2.5:3b"
BASE_URL = "http://localhost:11434/v1"
```

**vLLM:**
```python
MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
BASE_URL = "http://localhost:8000/v1"
```

## Model Comparison

| Model | Size | Best For | Features |
|-------|------|----------|----------|
| qwen2.5-3b-instruct | 3B | General tasks | Fast, efficient, tool calling |
| qwen2.5-coder-3b-instruct | 3B | Code generation | Optimized for programming tasks |
| qwen3-vl-2b-instruct | 2B | Vision + reasoning | Image analysis, lightweight |

## Features

| Feature | Cloud | Local | Notes |
|---------|-------|-------|-------|
| Text generation | ✓ | ✓ | Streaming supported |
| Tool calling | ✓ | ✓ | Parallel execution |
| Image analysis | ✓ | ✓ | Base64 required for local |
| Structured output | ✓ | ✓ | JSON mode |
| Multi-turn conversations | ✓ | ✓ | Memory management |
| Code generation | ✓ | ✓ | Specialized coder models |
| Long context | ✓ | ✓ | Up to 32K tokens |
| Batch processing | ✓ | ✓ | Async supported |
| Reasoning | ✓ | ✓ | Thinking process visible |

## Image Analysis

**Cloud (DashScope API):**
- Supports direct image URLs
- More efficient (~85 tokens)

**Local (LM Studio/vLLM/Ollama):**
- Requires base64-encoded images
- Uses more tokens (~750-1500 depending on image size)
- Automatic fallback in `image_agent.py`

```python
# Automatic URL → base64 fallback
agent.print_response(
    "Analyze this image",
    images=[Image(url="https://example.com/image.jpg")],
)
```

## Cloud Models

**Qwen-Plus:** General purpose, balanced performance
**Qwen-Turbo:** Faster, lower cost
**Qwen-Max:** Highest quality
**Qwen-Coder-Plus:** Code generation optimized
**Qwen-Long:** Up to 1M token context
**Qwen-VL-Plus:** Vision + language
**QwQ-32B-Preview:** Advanced reasoning
