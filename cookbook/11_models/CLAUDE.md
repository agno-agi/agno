# CLAUDE.md - Models Cookbook

Instructions for Claude Code when testing the models cookbooks.

---

## Overview

This folder contains **model provider** examples - how to use every supported LLM provider with Agno.

**Total Examples:** 667 (largest folder!)
**Organization:** By provider

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/11_models/openai/basic.py
```

---

## Provider Coverage

| Provider | Count | Key |
|:---------|------:|:----|
| `aimlapi/` | 12 | AIMLAPI_API_KEY |
| `anthropic/` | 41 | ANTHROPIC_API_KEY |
| `aws/` | 25 | AWS credentials |
| `azure/` | 25 | AZURE_* keys |
| `cerebras/` | 14 | CEREBRAS_API_KEY |
| `cohere/` | 17 | CO_API_KEY |
| `deepinfra/` | 9 | DEEPINFRA_API_KEY |
| `deepseek/` | 11 | DEEPSEEK_API_KEY |
| `fireworks/` | 9 | FIREWORKS_API_KEY |
| `google/` | 58 | GOOGLE_API_KEY |
| `groq/` | 26 | GROQ_API_KEY |
| `huggingface/` | 9 | HF_TOKEN |
| `ibm/` | 13 | IBM credentials |
| `litellm/` | 22 | Various |
| `llama_cpp/` | 7 | Local |
| `lmstudio/` | 11 | Local |
| `meta/` | 35 | META credentials |
| `mistral/` | 18 | MISTRAL_API_KEY |
| `nebius/` | 13 | NEBIUS_API_KEY |
| `nvidia/` | 9 | NVIDIA_API_KEY |
| `ollama/` | 21 | Local |
| `openai/` | 63 | OPENAI_API_KEY |
| + 10 more... | | |

---

## Testing Priorities

### Most Common (High Priority)
- `openai/` - Most widely used
- `anthropic/` - Claude models
- `google/` - Gemini models

### Local Models (No API Key)
- `ollama/` - Local inference
- `llama_cpp/` - Local GGUF
- `lmstudio/` - Local GUI

### Cloud Providers
- `aws/` - Bedrock
- `azure/` - Azure OpenAI
- `groq/` - Fast inference

---

## Common Patterns

Each provider folder typically has:
- `basic.py` - Simple completion
- `async_basic.py` - Async variant
- `streaming.py` - Streaming responses
- `tool_use.py` - Function calling
- `structured_output.py` - Pydantic output
- `image_*.py` - Vision/multimodal

---

## Notes

- This folder is for **provider coverage**, not features
- Test basic.py first to verify API key works
- Some providers have rate limits
- Local models (Ollama, llama_cpp) require setup
