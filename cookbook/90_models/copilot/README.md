# GitHub Copilot Model Provider

Use GitHub Copilot as a model provider in Agno.

## Authentication

The provider needs a GitHub token with Copilot access. It **automatically** exchanges this token for a short-lived Copilot access token and refreshes it when it expires — you never have to manage tokens manually.

Set the `GITHUB_COPILOT_TOKEN` environment variable:

```bash
export GITHUB_COPILOT_TOKEN="ghp_..."
```

Or pass it directly:

```python
from agno.models.copilot import CopilotChat

model = CopilotChat(id="gpt-4.1", github_token="ghp_...")
```

## String Syntax

```python
from agno.agent import Agent

agent = Agent(model="copilot:gpt-4.1")
```

## Examples

| File | Description |
|------|-------------|
| `basic.py` | Basic usage with sync, async, and streaming |
| `tool_use.py` | Agent with web search tools |
| `structured_output.py` | Structured output with Pydantic schema |
