# OpenUI client for Agno AG-UI

This example renders an Agno agent as generative UI with
[OpenUI](https://www.openui.com/). Agno owns the agent, tools, conversation
history, and AG-UI event stream. OpenUI owns the component prompt, streaming
parser, renderer, themes, and browser interactions.

The result is a complete chat client that can render charts, send follow-up
actions as new turns, validate forms locally, and submit their values back to
the same Agno conversation.

## Architecture

```text
React AgentInterface
  -> POST /agui with RunAgentInput
  -> Agno AgentOS + AGUI
  -> OpenAI model returns OpenUI Lang in AG-UI text events
  -> OpenUI parser and renderer stream interactive React components
```

`frontend/src/agno.ts` wraps OpenUI's `agUIAdapter` with a small
renderer-facing filter. It forwards text, tool, and error events while
suppressing run metadata and Agno's empty tool-parent text envelope. This
keeps fast tool results paired with their tool call in the OpenUI timeline.
The client also sends empty `state` and `forwardedProps` objects because
Agno's `RunAgentInput` model expects those AG-UI extension containers.

## Prerequisites

- Python 3.9 or newer
- Node.js 20.19 or newer, or Node.js 22.12 or newer
- An `OPENAI_API_KEY`

From the repository root, install Agno's demo environment:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

`OPENAI_MODEL` is optional and defaults to `gpt-5.5`.

## Run

Install the frontend dependencies and generate the OpenUI system prompt:

```bash
cd cookbook/05_agent_os/16_agui/openui/frontend
npm install
npm run generate:prompt
```

In one terminal, start the Agno server from the repository root:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/openui/server.py
```

In another terminal, start the frontend:

```bash
cd cookbook/05_agent_os/16_agui/openui/frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/agui` and
`/status` to AgentOS on port 7777.

## What to try

- **Chart + follow-ups:** renders Q1-Q4 revenue and two clickable next steps.
- **Validated form:** renders required project name, team size, and notes
  fields. Submit once while empty to see local validation, then use
  `Aurora-731`, `7`, and `Prioritize accessibility and charts` to send one
  structured turn back to Agno.
- **Use an Agno tool:** calls `get_quarterly_revenue` on the Python agent and
  renders its result as a chart.

The generated prompt and component spec are build artifacts. Regenerate them
after changing `frontend/src/library.ts`.

## Verify

```bash
cd cookbook/05_agent_os/16_agui/openui/frontend
npm run typecheck
npm test
npm run build
```

The example uses `@openuidev/react-ui` 0.13.6 and Agno 2.9.0. See the
[OpenUI documentation](https://www.openui.com/docs) and the
[Agno AG-UI documentation](https://docs.agno.com/agent-os/interfaces/agui/overview)
for the underlying APIs.
