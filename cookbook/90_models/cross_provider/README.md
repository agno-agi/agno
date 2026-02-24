# Cross-Provider Interoperability

Cookbooks demonstrating cross-provider tool message interoperability — switching
LLM providers mid-session while preserving tool call history, knowledge, and reasoning.

## Prerequisites

All cookbooks require API keys for the three major providers:

```bash
export GOOGLE_API_KEY=...
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

## Cookbooks

### gemini_to_openai_tool_use.py

Basic two-provider switch: Gemini makes tool calls, OpenAI consumes the results.

```bash
.venvs/demo/bin/python cookbook/90_models/cross_provider/gemini_to_openai_tool_use.py
```

### gemini_to_openai_responses.py

Two-provider switch using the OpenAI Responses API format.

```bash
.venvs/demo/bin/python cookbook/90_models/cross_provider/gemini_to_openai_responses.py
```

### three_provider_tool_cycle.py

Full three-provider cycle: Gemini -> OpenAI -> Claude -> Gemini. Each provider
performs a calculator operation and the final turn summarizes all results.

```bash
.venvs/demo/bin/python cookbook/90_models/cross_provider/three_provider_tool_cycle.py
```

### cross_provider_multi_tool.py

Parallel multi-tool calls (Calculator + YFinance) across providers. Gemini makes
parallel tool calls, Claude calculates ratios, OpenAI summarizes.

```bash
.venvs/demo/bin/python cookbook/90_models/cross_provider/cross_provider_multi_tool.py
```

### cross_provider_knowledge.py

Knowledge/RAG queries across provider switches. All three providers query the
same LanceDB knowledge base within a single session.

```bash
.venvs/demo/bin/python cookbook/90_models/cross_provider/cross_provider_knowledge.py
```

### cross_provider_reasoning.py

Reasoning/thinking models across provider switches. Claude uses extended thinking,
then OpenAI and Gemini continue the conversation with full history preserved.

```bash
.venvs/demo/bin/python cookbook/90_models/cross_provider/cross_provider_reasoning.py
```

## How It Works

Cross-provider interoperability relies on two mechanisms:

1. **Canonical storage**: All tool results are stored in Agno's canonical Message
   format (one Message per tool call, with `tool_call_id` and `tool_name`).

2. **Provider-specific formatting**: Each provider's formatter normalizes incoming
   messages before converting them. Gemini's combined tool message format (multiple
   tool results in one Message) is automatically split into canonical form before
   being processed by other providers.

This means you can freely switch providers mid-session — tool call history,
knowledge search results, and conversation context are all preserved.
