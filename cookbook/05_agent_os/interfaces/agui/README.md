# AG-UI Cookbook

Examples for `interfaces/agui` in AgentOS.

## Files
- `agent_with_media.py` — Accept multimodal user input (image, audio, video, document).
- `agent_with_tools.py` — Agent with backend tools.
- `agentic_chat.py` — Chat with frontend tools (change_background) and backend tools (get_weather).
- `backend_tool_rendering.py` — Render backend tools in frontend via useRenderTool.
- `basic.py` — Basic agent setup.
- `human_in_the_loop.py` — HITL with confirmation and user input.
- `multiple_instances.py` — Multiple agent instances.
- `reasoning_agent.py` — Agent with reasoning/thinking display.
- `research_team.py` — Multi-agent research team.
- `shared_state.py` — Shared state between agents.
- `showcase.py` — Single server exposing all Dojo demo endpoints.
- `state_events.py` — Outbound state synchronization via STATE_SNAPSHOT + STATE_DELTA events.
- `structured_output.py` — Structured output schema.
- `team_state_events.py` — Team state synchronization.
- `tool_based_generative_ui.py` — Generative UI using tool-based approach.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (Postgres, Redis, Slack, or MCP servers).
- For Dojo compatibility, run `showcase.py` on port 9001.
