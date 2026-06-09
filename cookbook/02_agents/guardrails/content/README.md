# Content Guardrail

Examples of using ContentGuardrail to detect jailbreak attempts, off-topic messages, and toxic content. Uses pattern matching and keyword analysis for fast, offline content filtering.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via `direnv allow`.
- Use `.venvs/demo/bin/python` to run cookbook examples.

## Files

- jailbreak.py - Detect and block jailbreak and prompt injection attempts.
- off_topic.py - Restrict agent to specific allowed topics.
- dry_run.py - Log content violations without blocking.
- post_hook.py - Validate model output for toxicity.
- on_fail.py - Custom callback when content violations occur.
