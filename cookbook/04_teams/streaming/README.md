# Team Streaming

Real-time response streaming from teams for interactive applications.

## Setup

```bash
pip install agno openai
```

Set your API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams can stream responses and events in real-time:

```python
from agno.team import Team

team = Team(
    members=[agent1, agent2],
)

# Stream response
for delta in team.run("Analyze market trends", stream=True, stream_events=True):
    print(delta.content, end="")
```

## Examples

- **[01_team_streaming.py](./01_team_streaming.py)** - Basic team response streaming
- **[02_events.py](./02_events.py)** - Team event streaming
- **[03_route_mode_events.py](./03_route_mode_events.py)** - Route mode event streaming
- **[04_async_team_streaming.py](./04_async_team_streaming.py)** - Asynchronous team streaming
- **[05_async_team_events.py](./05_async_team_events.py)** - Asynchronous team events
