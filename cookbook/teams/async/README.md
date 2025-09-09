# Team Modes

Team modes determine how agents work together to complete tasks.

## Setup

```bash
pip install agno openai
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams support three coordination modes:

```python
from agno.team import Team

team = Team(members=[agent1, agent2])
```

## Examples

- **[01_async_coordinated_team.py](./01_async_coordinated_team.py)** - Asynchronous coordinated team example
- **[02_async_delegate_to_all_members.py](./02_async_delegate_to_all_members.py)** - Asynchronous delegation to all members example
- **[03_async_respond_directly.py](./03_async_respond_directly.py)** - Asynchronous direct-member routing example
