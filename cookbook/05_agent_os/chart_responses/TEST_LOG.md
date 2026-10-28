# Test Log — chart_responses

Tested 2026-10-15 on branch `as/charts-example` with `.venvs/demo/bin/python`,
`OPENAI_API_KEY` set, and `gpt-5.6-luna`. Each example was imported to confirm
the AgentOS wiring, then the agent or team was run directly with a quick prompt
and the response was parsed for fenced chart blocks.

### agentos_chart_responses.py

**Status:** PASS

**Description:** Single agent with ChartTools. Imported the module and confirmed
the agent, quick prompts, and app are registered.

**Result:** Wiring valid. Chart behaviour for this file is covered by the
toolkit unit tests in `libs/agno/tests/unit/tools/test_chart.py`.

---

### agentos_chart_team.py

**Status:** PASS

**Description:** Ran the Growth Review Team with "Review the last 30 days of
usage and cost." Checked that each member called its data tool before
`create_chart`, and that the leader's content kept both member chart blocks.

**Result:** Two chart blocks in the leader response. Usage Analyst called
`get_daily_usage` then `create_chart` and produced a 30-row line chart with
runs, sessions, and active_users keyed by date. Cost Analyst called
`get_spend_by_model` then `create_chart` and produced a 3-row bar-stacked chart
of input and output tokens by model. The leader added a heading above each
chart and closed with a three-bullet summary. Run time about 59 seconds.

---

### agentos_platform_dashboard.py

**Status:** PASS

**Description:** Deleted the demo database, called `seed_activity()` (twelve
runs across three workers on gpt-5.6-luna, gpt-5.5, and gpt-5-mini, three
users, sessions backdated over seven days), confirmed a second call skips
seeding, then ran the dashboard agent with each of the three quick prompts and
checked tool order and chart data.

**Result:** Seeding took about 44 seconds. The metrics payload showed seven
daily rows, three models, and three agents. After removing the workers from
the served agents list, a fresh reseed still recorded traces for all three
workers and six tools, confirming tracing does not depend on registration. Each prompt fetched data before
charting:

- "Chart token usage by day and the model mix." produced a 7-row line chart of
  total tokens by date and a 3-slice pie of runs by model.
- "Show runs per agent for the last 7 days with average latency." produced a
  4-row horizontal bar chart of traces and average duration per agent.
- "Which tools were used most and how long did they take?" produced two 9-row
  horizontal bar charts, most-used tools and average tool duration.

Each prompt ran in 11 to 16 seconds.

---
