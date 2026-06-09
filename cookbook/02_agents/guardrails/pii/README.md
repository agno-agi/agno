# PII Detection Guardrail

Examples of using PIIDetectionGuardrail to detect and handle personally identifiable information (PII) in agent inputs and outputs. Supports block, mask, replace, and tokenize strategies.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via `direnv allow`.
- Use `.venvs/demo/bin/python` to run cookbook examples.

## Files

- detection.py - Block messages containing PII (default strategy).
- dry_run.py - Log PII detections without blocking.
- mask.py - Replace PII with asterisks of equal length.
- replace.py - Replace PII with descriptive type labels like [EMAIL], [SSN].
- pii_tokenize.py - Replace PII with reversible tokens for later restoration.
- hooks.py - PII guardrail in all hooks (pre, model, post) for defense in depth.
- post_hook.py - Check model output for PII leakage.
- on_fail.py - Custom callback when PII is detected.
