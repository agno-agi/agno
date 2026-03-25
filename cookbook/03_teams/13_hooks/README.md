# hooks

Examples for team workflows with hooks.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Files

- pre_hook_input.py - Demonstrates input validation and transformation pre-hooks.
- model_hook.py - Demonstrates function-based model hooks for context inspection and validation.
- post_hook_output.py - Demonstrates post hook output validation and transformation.
- stream_hook.py - Demonstrates post-hook notifications after streaming responses.
