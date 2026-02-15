# tools

Examples for team workflows in tools.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Files

- async_tools.py - Demonstrates async tools.
- custom_tools.py - Demonstrates custom tools.
- tool_call_limit.py - Demonstrates limiting total tool calls per Team run.
- tool_choice.py - Demonstrates forcing specific tool usage via tool_choice.
- member_tool_hooks.py - Demonstrates member tool hooks.
- tool_hooks.py - Demonstrates tool hooks.
