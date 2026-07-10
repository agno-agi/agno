# AG-UI Cookbook

Examples for connecting Agno agents and teams to frontend UIs using the AG-UI
protocol. AG-UI enables real-time streaming, tool execution, state synchronization,
and human-in-the-loop workflows between your backend agents and React frontends.

Works with any AG-UI compatible frontend, including [CopilotKit](https://github.com/CopilotKit/CopilotKit) and [Dojo](https://github.com/CopilotKit/CopilotKit/tree/main/examples/coagents-dojo).

## Quick Start

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

agent = Agent(
    name="Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/assistant.db"),
    instructions="You are a helpful assistant.",
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[AGUI(agent=agent)],
)

if __name__ == "__main__":
    agent_os.serve(port=9001, reload=True)
```

Run with `.venvs/demo/bin/python basic.py`, then connect your frontend to
`http://localhost:9001/Assistant/agui`.

## Examples

### Getting Started

Start here to learn the basics, then explore features as needed.

| File | Description |
|------|-------------|
| `basic.py` | Minimal agent with AG-UI interface |
| `agent_with_tools.py` | Agent with backend tools (web search) and frontend tools |
| `structured_output.py` | Agent with Pydantic output schema |
| `reasoning_agent.py` | Agent with reasoning model (o4-mini) and thinking display |
| `agent_with_media.py` | Multimodal input (images, audio, video, documents) via Gemini |

### Tools and Generative UI

Frontend tools execute in the browser; backend tools render via `useRenderTool`.

| File | Description |
|------|-------------|
| `agentic_chat.py` | Frontend tool (change_background) + backend tool (get_weather) |
| `backend_tool_rendering.py` | Backend tool rendered as weather card in frontend |
| `tool_based_generative_ui.py` | Frontend tool that generates styled haiku cards |

### State Synchronization

Agents can read and update session state, which syncs to the frontend in real-time
via `STATE_SNAPSHOT` and `STATE_DELTA` events.

| File | Description |
|------|-------------|
| `state_events.py` | Agent with `enable_agentic_state` that modifies recipe state |
| `shared_state.py` | Same pattern with pre-populated initial state |

### Human in the Loop

Tools can pause for user confirmation before executing.

| File | Description |
|------|-------------|
| `human_in_the_loop.py` | Tool with `requires_confirmation` that shows step selector UI |

### Teams

Multi-agent teams with AG-UI interface.

| File | Description |
|------|-------------|
| `research_team.py` | Researcher + Writer team with web search |
| `team_state_events.py` | Team with shared session state (recipe creator + nutrition advisor) |
| `multiple_instances.py` | Multiple agent instances on one server |

### Dojo Demos

These examples are designed for the Dojo frontend at `localhost:3002`.

| File | Description |
|------|-------------|
| `showcase.py` | All Dojo demo endpoints on one server (port 9001) |

Run `showcase.py` to expose all demos at their expected paths:
- `/agentic_chat` - Chat with tools
- `/backend_tool_rendering` - Weather card rendering
- `/human_in_the_loop` - Step confirmation UI
- `/tool_based_generative_ui` - Haiku generator
- `/shared_state` - Recipe state sync
- `/agentic_chat_reasoning` - Reasoning model
- `/agentic_chat_multimodal` - Image/audio/video input

## Running Examples

```bash
# Activate demo environment
source .venvs/demo/bin/activate

# Or use the demo Python directly
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/basic.py
```

Set your API keys:
```bash
export OPENAI_API_KEY="sk-..."
export GOOGLE_API_KEY="..."  # For agent_with_media.py (Gemini)
```

## Frontend Setup (Dojo)

To test with the Dojo frontend:

1. Clone and run Dojo:
   ```bash
   git clone https://github.com/CopilotKit/CopilotKit.git
   cd CopilotKit/examples/coagents-dojo
   pnpm install && pnpm dev
   ```

2. Run the showcase server:
   ```bash
   .venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/showcase.py
   ```

3. Open `http://localhost:3002` and select a demo.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection refused | Server not running | Start with `agent_os.serve(port=9001)` |
| No streaming | Missing `AGUI` interface | Add `interfaces=[AGUI(agent=agent)]` to AgentOS |
| State not syncing | Missing state config | Set `enable_agentic_state=True` on agent |
| HITL not working | Tool missing flag | Add `requires_confirmation=True` to tool decorator |
| Multimodal fails | Wrong model | Use Gemini or GPT-4o for image/audio input |
