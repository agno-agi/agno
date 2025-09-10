# Agent Teams

**Teams:** Groups of agents that collaborate to solve complex tasks through coordination, routing, or collaboration. This directory contains cookbooks demonstrating how to build and manage agent teams.

> Note: Fork and clone this repository if needed

## Getting Started

### 1. Setup Environment

```bash
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
pip install -U agno openai
```

### 2. Basic Team

```python
from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat

# Create team members
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Research and gather information",
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o"),
    role="Write clear summaries",
)

# Create team
team = Team(
    name="Research Team",
    members=[researcher, writer],
    model=OpenAIChat(id="gpt-4o"),
)

team.print_response("What are the latest trends in AI?")
```

## Examples

Multiple agents across various domains and use cases.

- **[basic/](./basic/)** - Essential team functionality
- **[db/](./db/)** - Database integration and persistence
- **[dependencies/](./dependencies/)** - Team dependency management
- **[distributed_rag/](./distributed_rag/)** - Distributed retrieval-augmented generation
- **[knowledge/](./knowledge/)** - Teams with shared knowledge bases
- **[memory/](./memory/)** - Persistent memory across team interactions
- **[metrics/](./metrics/)** - Team performance monitoring
- **[modes/](./modes/)** - Team coordination modes (route, coordinate, collaborate)
- **[multimodal/](./multimodal/)** - Teams handling text, images, audio, and video
- **[reasoning/](./reasoning/)** - Multi-agent reasoning and analysis
- **[search_coordination/](./search_coordination/)** - Coordinated search strategies
- **[session/](./session/)** - Session management and state
- **[state/](./state/)** - Team state management
- **[streaming/](./streaming/)** - Real-time response streaming from teams
- **[structured_input_output/](./structured_input_output/)** - Structured data processing
- **[tools/](./tools/)** - Teams with custom tools and tool coordination
