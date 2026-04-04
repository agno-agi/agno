# VLLM Reasoning Models

Cookbooks for using reasoning models served via vLLM.

## Prerequisites

1. A vLLM server running a reasoning-capable model:
   ```bash
   vllm serve Qwen/QwQ-32B --enable-reasoning --reasoning-parser deepseek_r1
   ```

2. Environment variables:
   ```bash
   export VLLM_API_KEY=your-key
   export VLLM_BASE_URL=http://localhost:8000/v1/
   ```

## Supported Reasoning Models

Models are detected as native reasoning models when:
- `enable_thinking=True` is set on the VLLM model (recommended), OR
- The model ID contains a known reasoning pattern: `qwq`, `qwen3`, `deepseek-r1`, `openthinker`

## Cookbooks

- `reasoning_agent.py` - Basic reasoning agent with vLLM
