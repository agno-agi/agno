# guardrails

Examples for team workflows in guardrails.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Files

- openai_moderation.py - Demonstrates openai moderation.
- pii_detection.py - Demonstrates pii detection.
- prompt_injection.py - Demonstrates prompt injection.
- [jev_guardrail.py](jev_guardrail.py) - Async Jev checks before the team leader runs. Requires `typesafe-sdk`, `TYPESAFE_API_KEY`, and `OPENAI_API_KEY`; see [Jev setup](../../90_models/typesafe/README.md).
