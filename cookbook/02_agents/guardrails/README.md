# Guardrails

Examples of using guardrails to validate, filter, and protect agent inputs and outputs. Guardrails can be attached as pre_hooks (input validation), model_hooks (context validation), and post_hooks (output validation).

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via `direnv allow`.
- Use `.venvs/demo/bin/python` to run cookbook examples.

## Subdirectories

- `pii/` - PII detection and handling (block, mask, replace, tokenize).
- `content/` - Content filtering (jailbreak detection, off-topic blocking, toxicity checks).
- `openai/` - OpenAI Moderation API integration.
- `classifier/` - LLM-based and ML-based content classification.

## Files

- defense_in_depth.py - Layered guardrails at pre, model, and post hooks for comprehensive protection.
- model_hook_guardrail.py - Using guardrails as model hooks to check context after RAG/memory.
