# Advisor Tools

Let an agent ask a user-defined list of advisor models for feedback, a second opinion, or additional context. The primary model decides when to consult an advisor and what to do with the answer.

## Overview

`AdvisorTools` registers two tools on the agent:

- `ask_advisor(advisor, prompt, context)` — ask one advisor a specific question
- `ask_all_advisors(prompt, context)` — ask every advisor the same question (parallel in async runs)

The advisor does not see the agent's conversation. The agent sends a self-contained prompt plus optional context (a draft, a plan, code), which keeps advisor calls cheap and focused. Advisor responses are advice, not instructions: the primary model decides what to incorporate.

Common patterns:

- **Cross-model review** — Have Gemini or Claude review an OpenAI agent's draft
- **Escalation** — A small, fast primary model escalates hard sub-problems to larger models
- **Multi-perspective feedback** — Poll several advisors and compare their answers
- **Domain-specific review** — Use a custom `system_message` to turn an advisor into a specialized reviewer

## Examples

| File | Description |
|------|-------------|
| `01_basic.py` | Simplest usage — a single advisor |
| `02_multi_advisor.py` | Multiple advisors with descriptions, polled together |
| `03_escalation.py` | Small primary model escalating to large advisors via model strings |
| `04_custom_system_message.py` | Custom `system_message` for a domain-specific reviewer |
| `05_async.py` | Async run — advisors queried in parallel |

## Quick Start

```python
from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.advisor import AdvisorTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        AdvisorTools(
            advisors=[Gemini(id="gemini-3.5-flash")],
        )
    ],
    instructions=[
        "After drafting a response, ask your advisor for a second opinion.",
        "Incorporate the suggestions you agree with into your final answer.",
    ],
)

agent.print_response("Explain how DNS works")
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `advisors` | `List[Union[Model, str]]` | required | Advisor models. Strings like `"openai:gpt-5.5"` are resolved via `get_model` |
| `descriptions` | `Dict[str, str]` | `None` | Advisor id to description, shown to the agent so it can pick the right advisor |
| `system_message` | `str` | Built-in advisor prompt | System message sent to advisors. Set to `None` to send none |
| `instructions` | `str` | Built-in instructions | Override the toolkit instructions shown to the agent |
| `add_instructions` | `bool` | `True` | Whether to add the toolkit instructions to the agent |
| `ask_all_advisors` | `bool` | `True` | Whether to register the `ask_all_advisors` tool |

## Advisor Ids

Each advisor is listed by its model id (e.g. `gemini-3.5-flash`). If two advisors share a model id, the later one is listed as `provider:model-id`. Exact duplicates raise an error.

## Running

```bash
# Ensure the demo environment is set up
./scripts/demo_setup.sh

# Run any example
.venvs/demo/bin/python cookbook/91_tools/advisor_tools/01_basic.py
```
