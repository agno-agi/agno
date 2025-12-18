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

Teams organized by functionality and use case.

### Core Functionality
- **[basic_flows/](./basic_flows/)** - Basic team coordination patterns and flows
- **[async_flows/](./async_flows/)** - Asynchronous team execution with `arun` method
- **[streaming/](./streaming/)** - Real-time response streaming and event handling
- **[structured_input_output/](./structured_input_output/)** - Structured data processing with Pydantic
- **[tools/](./tools/)** - Custom tools and tool coordination across team members
- **[other/](./other/)** - Input formats, response handling, and basic operations

### Knowledge, Memory and Sessions
- **[knowledge/](./knowledge/)** - Teams with shared knowledge bases
- **[memory/](./memory/)** - Persistent memory management across interactions
- **[session/](./session/)** - Session management and persistence
- **[state/](./state/)** - Shared state management across team members
- **[dependencies/](./dependencies/)** - Runtime dependency injection and context management

### Advanced Patterns
- **[distributed_rag/](./distributed_rag/)** - Distributed retrieval-augmented generation
- **[search_coordination/](./search_coordination/)** - Coordinated search across agents and sources
- **[reasoning/](./reasoning/)** - Multi-agent reasoning and analysis
- **[multimodal/](./multimodal/)** - Teams handling text, images, audio, and video

### Operations
- **[metrics/](./metrics/)** - Team performance monitoring and metrics collection
- **[hooks/](./hooks/)** - Pre and post-processing hooks for input/output
- **[guardrails/](./guardrails/)** - Safety guardrails (moderation, PII, prompt injection)
