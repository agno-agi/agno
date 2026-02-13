# Test Log — 08_guardrails

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| custom_guardrail.py | PASS | Custom guardrail blocks "bomb" keyword, allows normal password security question |
| openai_moderation.py | PASS | OpenAI moderation blocks hate speech and violent image content |
| output_guardrail.py | PASS | Output guardrail checks for clean architecture response quality |
| pii_detection.py | PASS | PII detection blocks SSN in input, agent advises secure handling |
| prompt_injection.py | PASS | Detects jailbreak and subtle injection attempts, blocks appropriately |
