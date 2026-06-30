# Model Feedback Tools

Get a "second opinion" from another AI model during a conversation. The primary agent can call one or more secondary models to critique its response before finalizing.

## Overview

`ModelFeedbackTools` sends the current conversation context to a secondary model and returns structured feedback (ratings, suggestions, and an overall assessment). This is useful for:

- **Cross-model review** — Have Gemini review an OpenAI agent's response (or vice versa)
- **Multi-perspective feedback** — Query multiple models in parallel for diverse viewpoints
- **Domain-specific critique** — Use a custom system prompt to focus on specific quality criteria
- **Self-review** — Use a cheaper/faster model from the same provider as a reviewer

## Examples

| File | Description |
|------|-------------|
| `01_basic.py` | Simplest usage — single feedback model |
| `02_multi_model.py` | Parallel feedback from Gemini + Claude |
| `03_custom_aspects.py` | Custom evaluation criteria and system prompt |
| `04_focused_feedback.py` | Using the `focus` parameter for targeted review |
| `05_self_review.py` | Same-provider review with a different model |

## Quick Start

```python
from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=Gemini(id="gemini-2.0-flash"),
        )
    ],
    instructions=[
        "After drafting a response, use the get_feedback tool.",
        "Incorporate the feedback into your final answer.",
    ],
)

agent.print_response("Explain how DNS works")
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `Model` | — | Single feedback model |
| `models` | `List[Model]` | — | Multiple feedback models (queried in parallel) |
| `aspects` | `List[str]` | `["accuracy", "completeness", "clarity"]` | Evaluation criteria |
| `system_prompt` | `str` | Built-in critique prompt | Override the review prompt entirely |
| `include_system_messages` | `bool` | `False` | Include system messages in context sent to reviewer |
| `max_messages` | `int` | `None` | Limit conversation history sent to reviewer |

## Feedback Format

The tool returns structured JSON:

```json
{
  "model": "gemini-2.0-flash",
  "overall_rating": 8,
  "aspects": {
    "accuracy": { "rating": 9, "comment": "Factually correct" },
    "completeness": { "rating": 7, "comment": "Missing edge cases" },
    "clarity": { "rating": 8, "comment": "Well structured" }
  },
  "suggestions": ["Add a concrete example", "Mention caching"],
  "summary": "Solid explanation, could use a practical example."
}
```

When using multiple models, feedback is grouped:

```json
{
  "feedback": [
    { "model": "gemini-2.0-flash", "overall_rating": 8, ... },
    { "model": "claude-sonnet-4-5-20250514", "overall_rating": 7, ... }
  ]
}
```

## Running

```bash
# Ensure the demo environment is set up
./scripts/demo_setup.sh

# Run any example
.venvs/demo/bin/python cookbook/91_tools/model_feedback_tools/01_basic.py
```
