# Toolkit Development Guide

This directory contains all Agno toolkits. Follow these patterns exactly.

---

## Quick Reference

```bash
# Run tests
pytest libs/agno/tests/unit/tools/

# Format and validate
./scripts/format.sh && ./scripts/validate.sh

# Cookbook location
cookbook/91_tools/<toolkit_name>_tools.py
```

---

## Architecture

```
Agent(tools=[MyToolkit()])
  ↓
agent._tools.parse_tools()
  ├── Generate JSON schema from function signature
  ├── Docstrings → tool descriptions (LLM sees these!)
  └── De-duplicate by name (first wins)
  ↓
Model receives: [{name, description, parameters}]
  ↓
FunctionCall.execute()
  ├── Inject: agent, team, run_context, fc
  └── Return result string
```

**Key insight:** Method docstrings are parsed into the JSON schema the LLM sees. This is why toolkit docstrings are the ONLY exception to the "no docstrings" rule.

---

## Key Files (Read Before Modifying)

| File | Role |
|------|------|
| `toolkit.py` | Base class, registration |
| `function.py` | Function model, execute, schema generation |
| `agent/_tools.py` | parse_tools, tool resolution |

---

## Complete Skeleton

```python
"""
<ToolkitName> — one-line description.

Setup:
1. Install: `pip install <package>`
2. Set env var: `<ENV_VAR>=<value>` OR pass `<param>=<value>`.

Credentials:
- How to get credential, step by step
- Link to provider dashboard
"""

import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import sdk_package
except ImportError:
    raise ImportError("`sdk_package` not installed. Please install using `pip install sdk-package`")


class MyTools(Toolkit):
    """One-line description of toolkit.

    Args:
        api_key: API key for service. Falls back to MY_API_KEY env var.
        search: Enable search tool. Defaults to True.
        delete: Enable delete tool. Defaults to False (destructive).
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        search: bool = True,
        delete: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("MY_API_KEY")
        if not self.api_key:
            raise ValueError("MY_API_KEY not set")

        self.client = SomeClient(api_key=self.api_key)

        tools: List[Callable] = []
        if all or search:
            tools.append(self.search)
        if all or delete:
            tools.append(self.delete)

        super().__init__(name="my_tools", tools=tools, **kwargs)

    def search(self, query: str, max_results: int = 10) -> str:
        """Search for items matching query.

        Args:
            query: The search query.
            max_results: Maximum results to return. Defaults to 10.

        Returns:
            JSON with list of results.
        """
        try:
            results = self.client.search(query, limit=max_results)
            return json.dumps(results)
        except sdk_package.APIError as e:
            logger.error(f"API error in search: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Unexpected error in search")
            return json.dumps({"error": str(e)})
```

---

## The 30 Rules (Condensed)

### Tool Design
1. Boolean flags without `enable_` prefix (`search: bool` not `enable_search: bool`)
2. Destructive tools default False (optionally recommend `requires_confirmation_tools` in the docstring)
3. Handle clients internally, not injected
4. Text tools return `json.dumps()`; media tools return `ToolResult`
5. Use `logger.exception()` in except blocks; NEVER with `exc_info=True`
6. Reuse clients (create in `__init__`, not per-request)
7. Only guard optional deps; bundled (httpx, pydantic) always available
8. ImportError uses raw package name (not `agno[extras]`)
9. Don't remove public API — deprecate
10. Consistent defaults across related methods

### Implementation
11. Always pass `**kwargs` to `super().__init__()`
12. Use `httpx`, not `requests`
13. Add `instructions` for 5+ tools
14. Clean up temp directories
15. Return error JSON, not silent failure
16. Parameter parity across methods
17. No sync calls in async context
18. Read env vars at call time, not import time
19. Batch operations continue on single failure
20. Coerce `response.content` before string ops

### Design
21. Prefer no `all` param if ≤2 tools (some existing 2-tool toolkits keep it for API consistency)
22. Lazy client init for heavy SDKs (`_get_client()`)
23. Return error string, don't raise on missing context
24. Let SDK raise auth errors
25. Avoid heavy transitive deps (no langchain)
26. Use `run_context.session_state` for user context
27. Don't log sensitive queries
28. Google-style docstrings (Args, Returns)
29. Large toolkits: most tools default False
30. Cookbooks use `print_response(stream=True)`

---

## Security Defaults

```python
# Destructive → False
delete: bool = False
run_query: bool = False
send_message: bool = False
```

Shipped toolkits enforce safety through default-False flags: the user must
opt in to destructive tools at construction time. For extra protection users
can pass `requires_confirmation_tools=["delete"]` to any toolkit; mention
this in the class docstring for highly destructive tools (see shell.py).

---

## Docstring Format (LLM-Critical)

```python
def search_emails(self, query: str, max_results: int = 10) -> str:
    """Search emails matching a Gmail query string.

    Use Gmail search syntax: "from:user@example.com", "subject:hello".

    Args:
        query: Gmail search query (e.g. "from:user@example.com").
        max_results: Maximum number of results. Defaults to 10.

    Returns:
        JSON string with list of emails containing id, subject, sender.
    """
```

**Rules:**
- First line: imperative, concise
- Body: usage tips, examples (LLM reads this!)
- Args: one line per param, NO type hints (use `query:` not `query (str):`)
- Returns: describe structure
- Do NOT include `self` or auto-injected params (run_context, agent)

---

## Auth Patterns

### Pattern A: Simple API Key
```python
self.api_key = api_key or getenv("MY_API_KEY")
if not self.api_key:
    raise ValueError("MY_API_KEY not set")
self.client = Client(api_key=self.api_key)
```

### Pattern B: Let SDK Raise
```python
self.token = token or getenv("MY_TOKEN")
self.client = Client(self.token)  # SDK raises if invalid
```

### Pattern C: Connection Lifecycle
```python
class PostgresTools(Toolkit):
    _requires_connect = True

    def connect(self) -> None:
        self.conn = psycopg2.connect(self.connection_string)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
```

### Pattern D: Google OAuth
```python
from agno.tools.google.auth import google_authenticate
authenticate = google_authenticate("gmail")

@authenticate
def list_emails(self, query: str) -> str:
    return self.service.users().messages().list(userId="me", q=query).execute()
```

---

## Return Format (MANDATORY)

```python
# Success
return json.dumps({"id": "123", "status": "created"})
return json.dumps([{"name": "item1"}, {"name": "item2"}])

# Error (NEVER f-strings!)
return json.dumps({"error": str(e)})
return json.dumps({"error": "Item not found"})

# WRONG
return f"Error: {e}"
return f"Created item {id}"
```

**Exception:** Media tools use `ToolResult`:
```python
from agno.tools.function import ToolResult
return ToolResult(content="Generated image", images=[Image(url=url)])
```

---

## Error Handling (Two-Tier)

```python
try:
    result = self.client.api_call()
    return json.dumps(result)
except sdk.SpecificError as e:
    logger.error(f"API error: {e}")
    return json.dumps({"error": str(e)})
except Exception as e:
    logger.exception("Unexpected error")
    return json.dumps({"error": str(e)})
```

**NEVER:** `logger.exception()` + `exc_info=True` (double traceback)

---

## Thread Safety

**CRITICAL:** After `agent.deep_copy()`, stateful toolkits (Google, Slack) are SHARED.

For per-user isolation, override `_clone_for_run()`:
```python
def _clone_for_run(self) -> "Toolkit":
    clone = copy.copy(self)
    clone.service = None  # Force re-init
    clone._cache = {}     # Reset user-specific state
    return clone
```

---

## Testing Checklist

**Init tests:**
- Missing creds raises ValueError
- Env var fallback works
- Default tools registered (safe=on, destructive=off)
- `all=True` enables everything

**Method tests:**
- Success returns valid JSON
- API error returns `{"error": ...}`
- SDK called with correct args

**File:** `libs/agno/tests/unit/tools/test_<name>.py`

---

## Cookbook Rules

**Location:** `cookbook/91_tools/<name>_tools.py` (flat file; grouped services like Google use a subdirectory)

```python
"""<ToolkitName> — demonstrates <what>.

Setup:
    pip install agno[<extras>]
    export <ENV_VAR>=<value>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.<name> import <Name>Tools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[<Name>Tools()],
    markdown=True,
)

agent.print_response("Query here", stream=True)
```

**Rules:**
- Uses `OpenAIResponses` (not `OpenAIChat`)
- Uses `gpt-5.5` (not `gpt-4o`)
- Uses `print_response(stream=True)`
- Exercises multiple tools
- No emojis

---

## Reference Toolkits

| Pattern | Example |
|---------|---------|
| Simple API key | `arxiv.py`, `tavily.py` |
| OAuth flow | `google/gmail.py`, `slack.py` |
| Database connection | `postgres.py`, `redshift.py` |
| Sync + Async | `brandfetch.py` |
| Large toolkit (10+ tools) | `github.py`, `spotify.py` |
| Dynamic instructions | `slack.py` (`_build_instructions`) |

---

## Do NOT

- Use `List[Any]` for tools list
- Default destructive operations to True
- Use f-strings for error returns
- Add comments in `__init__` signature
- Use `requests` (use `httpx`)
- Guard bundled deps
- Add docstrings to private methods
- Use `OpenAIChat` or `gpt-4o` in cookbooks
- Add empty `if __name__ == "__main__": pass`
