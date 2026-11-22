# Chart Responses

Agno OS renders a fenced ```chart block in an agent's markdown response as an
interactive chart. `ChartTools` owns the schema, validation, and formatting:
the agent calls `create_chart` with structured data, the tool returns the
fenced block, and the agent includes it verbatim. No chart-schema prompt
engineering is needed, the toolkit ships its own usage instructions.

```python
from agno.tools.chart import ChartTools

agent = Agent(model=OpenAIResponses(id="gpt-5.6-luna"), tools=[ChartTools()], markdown=True)
```

Supported chart types: `bar`, `line`, `area`, `pie`, `bar-horizontal`,
`bar-stacked`, `area-stacked`.

## Files

| File | What it teaches |
|---|---|
| `agentos_chart_responses.py` | The smallest setup: one agent with ChartTools, served through AgentOS with quick prompts. |
| `agentos_chart_team.py` | A Team whose members each own a data tool and ChartTools; the leader assembles one multi-chart report. |
| `agentos_platform_dashboard.py` | An agent that chains AgentOSTools and ChartTools to chart real platform metrics from its own database. |

## Prerequisites

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

## Run

Each example serves AgentOS on port 7777. Open the chat page in Agno OS and
pick a quick prompt, or send one of the prompts listed below.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/chart_responses/agentos_chart_responses.py
.venvs/demo/bin/python cookbook/05_agent_os/chart_responses/agentos_chart_team.py
.venvs/demo/bin/python cookbook/05_agent_os/chart_responses/agentos_platform_dashboard.py
```

### agentos_chart_responses.py

A single data analyst agent. Ask for trends, comparisons, or usage and it
responds with a chart block plus one sentence of context before and after.
The revenue quick prompt asks for the total as a headline value, which the
chart card shows beside the title.

### agentos_chart_team.py

The Growth Review Team delegates to a Usage Analyst and a Cost Analyst. Each
member calls its own data tool (`get_daily_usage`, `get_spend_by_model`) and
charts the result. The leader includes every member chart block verbatim and
closes with a summary that ties usage to cost. The data tools return a fixed
sample dataset so the example runs without a warehouse; replace them with your
own queries.

Try: "Review the last 30 days of usage and cost."

### agentos_platform_dashboard.py

On first start, three worker agents on different models and tools run twelve
prompts for three users, and their sessions are backdated across the last seven
days. The Platform Dashboard agent then reads the deployment's own metrics with
`AgentOSTools` and charts them with `ChartTools`: tokens per day, model mix,
runs and latency per agent, and tool usage. The instructions require a data
fetch before every chart and map data shapes to chart types, so the model never
invents numbers.

Only the dashboard agent is served. The workers are plain agents used for
seeding; tracing is process-wide, so their runs are recorded without being
registered. Seeding is skipped when the database already has sessions. Delete
`tmp/agentos_platform_dashboard.db` to reseed.

Try: "Chart token usage by day and the model mix."

## Notes

- Keep chart data compact. The toolkit rejects empty data, non-flat rows, and
  series keys that are missing or non-numeric, and returns a validation error
  the model can act on.
- Pass `value` to show a preformatted headline figure beside the chart title,
  such as a total or the latest value ("200M", "$22.3K", "94%"). The toolkit
  tells the model to leave it out when no single number summarizes the chart.
- Numbers passed as strings are coerced to numbers for series keys, so a model
  that stringifies values still produces a valid chart.
- When a Team assembles member charts, instruct the leader to include the
  fenced blocks verbatim. The leader has no ChartTools of its own in the team
  example; it only composes.
