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

# Route: Direct tasks to the best agent
team = Team(members=[agent1, agent2], mode="route")

# Coordinate: Agents work sequentially 
team = Team(members=[agent1, agent2], mode="coordinate")

# Collaborate: Agents work together to reach consensus
team = Team(members=[agent1, agent2], mode="collaborate")
```

## Examples

- **[01_async_collaborate.py](./01_async_collaborate.py)** - Asynchronous collaborative mode
- **[02_async_coordinate.py](./02_async_coordinate.py)** - Asynchronous coordination mode
- **[03_async_route.py](./03_async_route.py)** - Asynchronous routing mode
