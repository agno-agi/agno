# AG-UI Cookbook

Examples for `interfaces/agui` in AgentOS.

## Files

### Agents
- `basic.py` — Basic agent setup.
- `agent_with_tools.py` — Agent with backend tools.
- `agent_with_media.py` — Accept multimodal user input (image, audio, video, document).
- `agentic_chat.py` — Chat with frontend tools (change_background) and backend tools (get_weather).
- `reasoning_agent.py` — Agent with reasoning/thinking display.
- `structured_output.py` — Structured output schema.
- `human_in_the_loop.py` — HITL with confirmation and user input.
- `backend_tool_rendering.py` — Render backend tools in frontend via useRenderTool.
- `tool_based_generative_ui.py` — Generative UI using tool-based approach.

### Teams
- `research_team.py` — Multi-agent research team.
- `team_with_client_tools.py` — Team with frontend-defined client tools (e.g., change_background).
- `team_state_events.py` — Team state synchronization.

### State & Multi-Instance
- `state_events.py` — Outbound state synchronization via STATE_SNAPSHOT + STATE_DELTA events.
- `shared_state.py` — Shared state between agents.
- `multiple_instances.py` — Multiple agent instances.

### Showcase
- `showcase.py` — Single server exposing all Dojo demo endpoints.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (Postgres, Redis, Slack, or MCP servers).

## Dojo Compatibility
Run `showcase.py` on port 9001 for full Dojo compatibility, or individual cookbooks with matching `prefix` parameters.
