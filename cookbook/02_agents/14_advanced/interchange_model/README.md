# Interchange Model

This cookbook demonstrates switching between different model providers within a single agent session while preserving tool call history.

## What it tests

An agent with `add_history_to_context=True` uses tools across multiple turns, switching models between turns. The history (including tool calls and results) must be correctly formatted for each provider.

## Providers covered

- **OpenAI Chat Completions** (`OpenAIChat`)
- **Anthropic Claude** (`Claude`)
- **Google Gemini** (`Gemini`)

## Scripts

| Script | Description |
|--------|-------------|
| `openai_claude.py` | Alternates between OpenAI Chat and Claude with tool calls |

## Prerequisites

- PostgreSQL running (for session persistence): `./cookbook/scripts/run_pgvector.sh`
- API keys set: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`

## Running

```bash
# Start the database
./cookbook/scripts/run_pgvector.sh

# Run the interchange test
.venvs/demo/bin/python cookbook/02_agents/14_advanced/interchange_model/openai_claude.py
```
