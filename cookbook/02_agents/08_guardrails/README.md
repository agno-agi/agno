# guardrails

Examples for input/output safety checks and policy enforcement.

## Files
- `custom_guardrail.py` - Demonstrates custom guardrail.
- `openai_moderation.py` - Demonstrates openai moderation.
- `output_guardrail.py` - Demonstrates output guardrail.
- `pii_detection.py` - Demonstrates pii detection.
- `prompt_injection.py` - Demonstrates prompt injection.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
