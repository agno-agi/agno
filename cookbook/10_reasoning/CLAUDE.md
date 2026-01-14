# CLAUDE.md - Reasoning Cookbook

Instructions for Claude Code when testing the reasoning cookbooks.

---

## Overview

This folder contains **reasoning model** examples - how to use chain-of-thought, reasoning tools, and reasoning-capable models (o1, o3, DeepSeek, etc.).

**Total Examples:** 94
**Organization:** By component (agents, models, teams, tools)

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/10_reasoning/agents/default_chain_of_thought.py
```

---

## Folder Structure

| Folder | Description |
|:-------|:------------|
| `agents/` | Reasoning agent patterns |
| `models/` | Model-specific reasoning (OpenAI o1/o3, DeepSeek, Gemini, Groq, etc.) |
| `teams/` | Reasoning in multi-agent teams |
| `tools/` | ReasoningTools integration |

---

## Model Coverage

### OpenAI
- o1, o1-pro, o3-mini, o4-mini
- GPT-4 with reasoning tools

### DeepSeek
- DeepSeek R1 reasoning model
- Various reasoning tasks

### Anthropic
- Claude with reasoning tools

### Google
- Gemini with reasoning

### Groq
- Fast reasoning with Llama

### Others
- Azure OpenAI, Ollama, Cerebras, xAI

---

## Key Patterns

### Default Chain of Thought
Built-in reasoning before responses.

### Reasoning Tools
Explicit think/analyze/plan tools.

### Reasoning Effort
Control reasoning depth (low/medium/high).

### Show Full Reasoning
Display reasoning steps in output.

---

## Testing Priorities

### High Priority
- `agents/default_chain_of_thought.py`
- `tools/reasoning_tools.py`
- `models/openai/o3_mini.py`

### Fun Examples
- `agents/strawberry.py` - Count letters
- `agents/is_9_11_bigger_than_9_9.py` - Math reasoning
- `agents/trolley_problem.py` - Ethical reasoning

---

## API Keys Required

| Provider | Key |
|:---------|:----|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google | `GOOGLE_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Groq | `GROQ_API_KEY` |
