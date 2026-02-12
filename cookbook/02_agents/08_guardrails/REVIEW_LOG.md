# REVIEW LOG — guardrails

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Summary

5 files reviewed. No code fixes required. All use v2.5 pre_hooks/post_hooks correctly.

## custom_guardrail.py

- **[FRAMEWORK]** `BaseGuardrail` at `guardrails/base.py:8` is correct ABC. Requires `check()` and `async_check()` methods — both implemented. `InputCheckError` and `CheckTrigger` from `agno.exceptions` are valid (`exceptions.py:122,134`). `pre_hooks=[TopicGuardrail()]` is correct Agent param (`agent.py:176`).
- **[QUALITY]** Strong example of custom guardrail pattern. Shows both sync and async check methods. Simple blocked-terms approach is educational without being complex. Uses `run_input.input_content` correctly.
- **[COMPAT]** `OpenAIResponses(id="gpt-5.2")` consistent with codebase.

## openai_moderation.py

- **[FRAMEWORK]** `OpenAIModerationGuardrail` at `guardrails/openai.py:12`, re-exported via `agno.guardrails.__init__`. `raise_for_categories` param exists for selective category filtering. `Image` from `agno.media` is correct. Multi-modal moderation (text + image) is supported.
- **[QUALITY]** Comprehensive 4-test suite covering safe content, violence, hate speech, and image moderation. Good use of custom categories. Note: Tests 2-3 print `[WARNING]` when guardrail blocks via pre_hooks (the InputCheckError is caught by the framework, not the try/except) — this is the expected pre_hooks behavior, not a test failure.
- **[COMPAT]** `OpenAIChat(id="gpt-4o-mini")` is valid. Async-only pattern for all tests.

## output_guardrail.py

- **[FRAMEWORK]** `OutputCheckError` at `exceptions.py:155` is correct. `CheckTrigger.OUTPUT_NOT_ALLOWED` exists. `post_hooks=[enforce_non_empty_output]` is valid — accepts both `BaseGuardrail` instances and plain callables (`agent.py:178`). `RunOutput` from `agno.run.agent` is correct type for post_hook functions.
- **[QUALITY]** Clean, minimal example. Shows function-based (non-class) post_hook pattern, complementing the class-based custom_guardrail. `run_output.content` is the correct field for checking agent output.
- **[COMPAT]** `OpenAIResponses(id="gpt-5.2")` consistent.

## pii_detection.py

- **[FRAMEWORK]** `PIIDetectionGuardrail` at `guardrails/pii.py:10`, re-exported via `agno.guardrails.__init__`. `mask_pii=True` param exists for PII masking mode (replaces PII with placeholders instead of blocking).
- **[QUALITY]** Excellent 8-test suite: SSN, credit card, email, phone, multiple PII, edge-case formatting, and mask mode. Most comprehensive guardrail cookbook. Mix of sync (`print_response`) and async (`main` wrapper) patterns.
- **[COMPAT]** `OpenAIChat(id="gpt-4o-mini")` is valid.

## prompt_injection.py

- **[FRAMEWORK]** `PromptInjectionGuardrail` at `guardrails/prompt_injection.py:9`, re-exported via `agno.guardrails.__init__`. Uses OpenAI's moderation-based injection detection.
- **[QUALITY]** Good 5-test suite covering normal request, basic injection, DAN-style, jailbreak, and subtle injection. Sync-only pattern (appropriate since no async-specific behavior). Tests cover the major injection categories.
- **[COMPAT]** `OpenAIChat(id="gpt-4o-mini")` is valid.

## Framework Files Checked

- `libs/agno/agno/agent/agent.py:176,178` — pre_hooks, post_hooks params (accept Union[Callable, BaseGuardrail, BaseEval])
- `libs/agno/agno/guardrails/__init__.py` — re-exports BaseGuardrail, OpenAIModerationGuardrail, PIIDetectionGuardrail, PromptInjectionGuardrail
- `libs/agno/agno/guardrails/base.py:8` — BaseGuardrail ABC (check + async_check)
- `libs/agno/agno/guardrails/openai.py:12` — OpenAIModerationGuardrail (raise_for_categories)
- `libs/agno/agno/guardrails/pii.py:10` — PIIDetectionGuardrail (mask_pii)
- `libs/agno/agno/guardrails/prompt_injection.py:9` — PromptInjectionGuardrail
- `libs/agno/agno/exceptions.py:122,134,155` — CheckTrigger, InputCheckError, OutputCheckError
