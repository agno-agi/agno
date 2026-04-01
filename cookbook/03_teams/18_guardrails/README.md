# guardrails

Examples for team workflows with guardrails.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Subdirectories

- `pii/` - PII detection with block and mask strategies.
- `content/` - Content filtering (jailbreak, toxicity) and prompt injection detection.
- `openai/` - OpenAI Moderation API integration.
- `classifier/` - LLM-based content classification.

## Files

- defense_in_depth.py - Layered guardrails at pre, model, and post hook stages.
- dry_run.py - Dry run mode where violations are logged but not blocked.
- model_hooks.py - Guardrails as model_hooks (checks after context is built).
- prompt_injection.py - Prompt injection detection (ContentGuardrail recommended, PromptInjectionGuardrail deprecated).
