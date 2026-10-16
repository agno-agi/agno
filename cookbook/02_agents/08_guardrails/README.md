# guardrails

Examples for input/output safety checks and policy enforcement.

## Files
- `custom_guardrail.py` - Demonstrates custom guardrail.
- `deepkeep_ai_firewall.py` - Demonstrates DeepKeep AI Firewall guardrails.
- [jev_guardrail.py](jev_guardrail.py) - Jev preset checks, custom questions, per-check thresholds, and input/output hooks.
- [jev_grounding.py](jev_grounding.py) - Check a generated answer against supplied evidence with Jev.
- `openai_moderation.py` - Demonstrates openai moderation.
- `output_guardrail.py` - Demonstrates output guardrail.
- `pii_detection.py` - Demonstrates pii detection.
- `prompt_injection.py` - Demonstrates prompt injection.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.
- Jev examples need Python 3.10+, `typesafe-sdk`, `TYPESAFE_API_KEY`, and `OPENAI_API_KEY`. See [Jev setup](../../90_models/typesafe/README.md).

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
