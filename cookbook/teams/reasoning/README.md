# Team Reasoning

Multi-agent reasoning and analysis.

## Setup

```bash
# install dep's based on your preferred model provider
pip install agno openai anthropic
```

Set your API keys:
```bash
export OPENAI_API_KEY=xxx
export ANTHROPIC_API_KEY=xxx
```

## Basic Integration

Teams can employ reasoning tools for structured analysis:

```python
from agno.team import Team
from agno.tools.reasoning import ReasoningTools

team = Team(
    members=[research_agent, analysis_agent],
    tools=[ReasoningTools()],
    reasoning=True,
)

team.print_response("Analyze the pros and cons of renewable energy")
```

## Examples

- **[01_reasoning_multi_purpose_team.py](./01_reasoning_multi_purpose_team.py)** - Multi-purpose reasoning team
- **[02_async_multi_purpose_reasoning_team.py](./02_async_multi_purpose_reasoning_team.py)** - Asynchronous reasoning team
