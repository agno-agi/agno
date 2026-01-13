# Structured Input Output

Structured data processing with teams using Pydantic models and schemas.

## Setup

```bash
pip install agno openai pydantic
```

Set your API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams can process and return structured data using Pydantic models:

```python
from agno.team import Team
from pydantic import BaseModel

class TaskInput(BaseModel):
    query: str
    priority: int

class TaskOutput(BaseModel):
    result: str
    confidence: float

team = Team(
    members=[agent1, agent2],
    output_schema=TaskOutput,
)

response = team.run(TaskInput(query="Analyze data", priority=1))
```

## Examples

- **[01_pydantic_model_as_input.py](./01_pydantic_model_as_input.py)** - Pydantic models as team input
- **[02_team_with_parser_model.py](./02_team_with_parser_model.py)** - Response parsing with models
- **[03_team_with_output_model.py](./03_team_with_output_model.py)** - Structured output models
- **[04_structured_output_streaming.py](./04_structured_output_streaming.py)** - Streaming structured output
- **[05_async_structured_output_streaming.py](./05_async_structured_output_streaming.py)** - Async structured streaming
- **[06_input_schema_on_team.py](./06_input_schema_on_team.py)** - Input schema validation
