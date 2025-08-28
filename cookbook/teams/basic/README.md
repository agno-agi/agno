# Basic Team Operations

Essential team functionality including input formats, response handling, and basic team coordination patterns.

## Setup

```bash
pip install agno openai
```

Set your API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams coordinate multiple agents to handle tasks:

```python
from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat

team = Team(
    members=[
        Agent(name="Researcher", role="Research information"),
        Agent(name="Writer", role="Write summaries")
    ],
    model=OpenAIChat(id="gpt-4o"),
    stream=True,
)

team.print_response("Analyze the current AI market trends")
```

## Examples

- **[few_shot_learning.py](./few_shot_learning.py)** - Teams with few-shot learning examples
- **[input_as_dict.py](./input_as_dict.py)** - Dictionary input format for multimodal content
- **[input_as_list.py](./input_as_list.py)** - List input format for multiple messages
- **[input_as_messages_list.py](./input_as_messages_list.py)** - Message list format
- **[response_as_variable.py](./response_as_variable.py)** - Capturing team responses in variables
- **[run_as_cli.py](./run_as_cli.py)** - Interactive CLI application with teams
- **[team_cancel_a_run.py](./team_cancel_a_run.py)** - Cancelling team execution
- **[team_exponential_backoff.py](./team_exponential_backoff.py)** - Retry with exponential backoff
