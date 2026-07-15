# Reasoning

Reasoning gives Agents the ability to "think" before responding and "analyze" the results of their actions (i.e. tool calls), greatly improving the Agents' ability to solve problems that require sequential tool calls.

Agno supports 2 approaches to reasoning:

1. Native Reasoning Models
2. Reasoning Tools

## Native Reasoning Models

Many modern models have built-in reasoning capabilities. Agno automatically extracts and surfaces reasoning content from these models:

- **Claude**: Use `thinking={"type": "enabled", "budget_tokens": 1024}` parameter
- **Gemini**: Use `thinking_budget=1024` and `include_thoughts=True` parameters
- **OpenAI o-series**: Models like `o3-mini` have native reasoning with `reasoning_effort` parameter
- **DeepSeek**: DeepSeek-reasoner models emit `<think>` tags automatically
- **Groq/Ollama**: Models like `deepseek-r1-distill` and `qwq` have native reasoning

See the [examples](./models/).

## Reasoning Tools

By giving a model a "think" tool, we can greatly improve its reasoning capabilities by providing a dedicated space for structured thinking. This is a simple, yet effective approach to add reasoning to non-reasoning models.

```python
from agno.agent import Agent
from agno.tools.reasoning import ReasoningTools

agent = Agent(
    model=...,
    tools=[ReasoningTools(add_instructions=True)],
)
```

See the [examples](./tools/).

## Teams with Reasoning

Teams can also use ReasoningTools for coordinated reasoning across multiple agents.

See the [examples](./teams/).
