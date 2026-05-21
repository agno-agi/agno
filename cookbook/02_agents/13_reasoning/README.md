# 13_reasoning

Examples for explicit multi-step reasoning behavior.

## Files
- `basic_reasoning.py` - Enable reasoning with configurable steps.
- `reasoning_with_model.py` - Use a separate reasoning model with step limits.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/13_reasoning/<file>.py`
