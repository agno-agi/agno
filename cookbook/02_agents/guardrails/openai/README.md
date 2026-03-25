# OpenAI Moderation Guardrail

Examples of using OpenAIModerationGuardrail to leverage OpenAI's moderation API for content safety. Detects violence, hate speech, self-harm, sexual content, and other policy violations.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via `direnv allow`.
- Use `.venvs/demo/bin/python` to run cookbook examples.

## Files

- moderation.py - Basic moderation using OpenAI's moderation API.
- category_filter.py - Filter specific content categories (violence, hate).
- dry_run.py - Log moderation flags without blocking.
- all_hooks.py - Moderation guardrail in all hooks (pre, model, post) for defense in depth.
- on_fail.py - Custom callback when moderation flags content.
