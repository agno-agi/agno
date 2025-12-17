# Remote Agents, Teams & Workflows

This cookbook demonstrates how to use Agno's remote execution capabilities to deploy agents, teams, and workflows as microservices. Remote agents allow you to:

- Deploy agents as independent services
- Scale agents independently based on load
- Share agents across multiple applications
- Centralize agent management and monitoring
- Build distributed AI systems

## Architecture

The remote agent pattern consists of two components:

1. **AgentOS Server** - Hosts agents, teams, and workflows via REST API
2. **Remote Runners** - Client-side proxies (`RemoteAgent`, `RemoteTeam`, `RemoteWorkflow`) that connect to the server

```
┌─────────────────┐         HTTP          ┌─────────────────┐
│   Your App      │ ◄──────────────────► │  AgentOS Server │
│                 │                       │                 │
│  RemoteAgent    │    arun("query")      │  Agent Instance │
│  RemoteTeam     │    + streaming        │  Team Instance  │
│  RemoteWorkflow │    + memory           │  Workflow       │
└─────────────────┘                       └─────────────────┘
```

## Setup

### 1. Start the AgentOS Server

The server hosts the actual agent, team, and workflow instances:

```bash
python cookbook/agent_os/remote/server.py
```

Server will start on `http://localhost:7778` with:
- Assistant agent (calculator tools, knowledge base, memory)
- Researcher agent (web search tools)
- Research team (coordinates assistant + researcher)
- QA workflow (simple Q&A pipeline)

### 2. Run Examples

Once the server is running, you can run any of the client examples:

```bash
# Remote agent examples
python cookbook/agent_os/remote/01_remote_agent.py

# Remote team examples
python cookbook/agent_os/remote/02_remote_team.py

# AgentOS gateway (combines remote and local agents)
python cookbook/agent_os/remote/03_agent_os_gateway.py
```

## Examples

### Remote Agent (`01_remote_agent.py`)

Call agents hosted on a remote AgentOS instance:

```python
from agno.agent import RemoteAgent

# Connect to remote agent
agent = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="assistant-agent",
)

# Use it like a local agent
response = await agent.arun(
    "What is the capital of France?",
    user_id="user-123",
    session_id="session-456",
)
print(response.content)

# Stream responses
async for chunk in agent.arun(
    "Tell me a story",
    stream=True,
    stream_events=True,
):
    if hasattr(chunk, "content") and chunk.content:
        print(chunk.content, end="", flush=True)
```

### Remote Team (`02_remote_team.py`)

Call teams hosted on a remote AgentOS instance:

```python
from agno.team import RemoteTeam

# Connect to remote team
team = RemoteTeam(
    base_url="http://localhost:7778",
    team_id="research-team",
)

# Use it like a local team
response = await team.arun(
    "Research the latest AI trends and summarize",
    user_id="user-123",
    session_id="session-456",
)
print(response.content)
```

### AgentOS Gateway (`03_agent_os_gateway.py`)

Build a gateway that combines remote and local agents:

```python
from agno.agent import RemoteAgent
from agno.team import RemoteTeam
from agno.workflow import RemoteWorkflow, Workflow
from agno.os import AgentOS

# Mix remote and local resources
agent_os = AgentOS(
    description="Gateway combining remote and local agents",
    agents=[
        # Remote agents from another server
        RemoteAgent(base_url="http://localhost:7778", agent_id="assistant-agent"),
        RemoteAgent(base_url="http://localhost:7778", agent_id="researcher-agent"),
    ],
    teams=[
        # Remote teams
        RemoteTeam(base_url="http://localhost:7778", team_id="research-team"),
    ],
    workflows=[
        # Mix remote and local workflows
        RemoteWorkflow(base_url="http://localhost:7778", workflow_id="qa-workflow"),
        advanced_workflow,  # Local workflow defined in this app
    ],
)

# Serve the gateway
agent_os.serve(port=7777)
```

Now you have a gateway on port 7777 that orchestrates:
- Remote agents from port 7778
- Local workflows defined in the gateway
- All accessible via a single API

## Use Cases

### 1. Microservices Architecture

Deploy specialized agents as independent services:

```python
# Service 1: Data processing agents
AgentOS(agents=[data_processor, validator])

# Service 2: Customer service agents
AgentOS(agents=[support_agent, escalation_agent])

# Main app: Uses remote agents
app = AgentOS(
    agents=[
        RemoteAgent(base_url="http://data-service", agent_id="processor"),
        RemoteAgent(base_url="http://support-service", agent_id="support"),
    ]
)
```

### 2. Shared Agent Infrastructure

Multiple applications using the same agents:

```python
# Central AgentOS server
agent_os = AgentOS(agents=[research_agent, writing_agent])

# App 1: Blog generator
blog_app = AgentOS(
    agents=[RemoteAgent(..., agent_id="research_agent")],
)

# App 2: Report generator
report_app = AgentOS(
    agents=[RemoteAgent(..., agent_id="research_agent")],
)
```

### 3. Independent Scaling

Scale compute-intensive agents separately:

```
┌───────────────┐      ┌─────────────────┐
│  Web UI       │      │  Heavy Agent    │
│  (1 instance) │ ◄───►│  (5 instances)  │
│               │      │  Load Balanced  │
└───────────────┘      └─────────────────┘
```

### 4. Development Workflow

Run agents locally during development, deploy remotely in production:

```python
# Development - local agent
agent = Agent(model=OpenAIChat(id="gpt-4o"), tools=[...])

# Production - same agent, remote execution
agent = RemoteAgent(base_url=PRODUCTION_URL, agent_id="agent-id")
```
