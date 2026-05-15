# Gemini Interactions API

Examples using Google's Interactions API with Agno.

The Interactions API is a new primitive that provides:

- **Server-side conversation history** - Only send new messages each turn, not the full history
- **Implicit caching** - Prior turns are cached server-side for lower costs and latency
- **Typed execution steps** - Responses contain discriminated content types for better observability
- **Background execution** - Support for long-running tasks

## Setup

```bash
pip install -U google-genai
export GOOGLE_API_KEY=your-api-key
```

Requires `google-genai>=1.55.0`.

## Examples

| File | Description |
|------|-------------|
| `basic.py` | Basic text generation (sync, async, streaming) |
| `tool_use.py` | Function calling with external tools |
| `multi_turn.py` | Multi-turn conversation with server-side history |
| `thinking.py` | Reasoning/thinking mode |
| `search.py` | Built-in Google Search tool |

## Usage

```python
from agno.agent import Agent
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(id="gemini-2.5-flash"),
    markdown=True,
)
agent.print_response("Hello!")
```

## Notes

- The Interactions API is experimental and may change in future versions
- Interactions are stored server-side for 55 days (paid) / 1 day (free tier)
- System instructions and tools must be re-sent each turn (they are interaction-scoped)
- Set `store=False` to disable server-side persistence
