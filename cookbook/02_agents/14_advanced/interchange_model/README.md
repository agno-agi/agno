# Interchange Model

This cookbook demonstrates switching between different model providers within a single agent session while preserving tool call history.

## What it tests

An agent with `add_history_to_context=True` uses tools across multiple turns, switching models between turns. The history (including tool calls and results) must be correctly formatted for each provider.

## Providers covered

- **OpenAI Chat Completions** (`OpenAIChat`)
- **OpenAI Responses** (`OpenAIResponses`)
- **Anthropic Claude** (`Claude`)
- **Google Gemini** (`Gemini`)
- **AWS Claude** (via `agno.models.aws.Claude`)

## Scripts

| Script                     | Description                                                                                  |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| `openai_claude.py`         | Alternates between OpenAI Chat and Claude with tool calls                                    |
| `openai_chat_responses.py` | Alternates between OpenAI Chat and OpenAI Responses with tool calls                          |
| `openai_gemini.py`         | Alternates between OpenAI Chat and Gemini with tool calls                                    |
| `claude_gemini.py`         | Alternates between Claude and Gemini with tool calls                                         |
| `all_providers.py`         | Cycles through OpenAI Chat, OpenAI Responses, Claude, Gemini, and AWS Claude with tool calls |

## Prerequisites

- PostgreSQL + pgvector running (for session persistence): `./cookbook/scripts/run_pgvector.sh`
- API keys set: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`
- Optional: `AGNO_POSTGRES_URL` (defaults to `postgresql+psycopg://ai:ai@localhost:5532/ai`)

## Running

```bash
# Start the database
./cookbook/scripts/run_pgvector.sh

# Run one of the interchange scripts
.venvs/demo/bin/python cookbook/02_agents/14_advanced/interchange_model/openai_claude.py

# Or run the full provider cycle
.venvs/demo/bin/python cookbook/02_agents/14_advanced/interchange_model/all_providers.py
```
