# AgentOS showcase

This lesson assembles the curriculum into one coherent AgentOS process. It
serves a pgvector-backed Agno documentation assistant, a current web-and-finance
researcher, and a finance Team while storing sessions, traces, knowledge, and
evaluation results in PostgreSQL.

The app always enables Bearer authentication with `OS_SECURITY_KEY` for
protected REST requests. It also enables AgentOS tracing and runs one real
`AccuracyEval` before the server starts.

## Files

| File | What it teaches |
|---|---|
| `_agents.py` | Shared PostgreSQL storage, pgvector documentation knowledge, Agno Assist, and Sage. |
| `_teams.py` | A finance Team combining Sage with a focused market-data specialist. |
| `demo.py` | One secured and traced AgentOS plus knowledge preparation and a stored accuracy evaluation. |

## Prerequisites

- Install the demo environment with `./scripts/demo_setup.sh`.
- Start PostgreSQL with pgvector on port 5532:

  ```bash
  ./cookbook/scripts/run_pgvector.sh
  ```

- Export `OPENAI_API_KEY` for Agno Assist, embeddings, the finance specialist,
  and the Team leader.
- Export `ANTHROPIC_API_KEY` for Sage and the accuracy judge.
- Export a private `OS_SECURITY_KEY`; protected REST requests must send it as
  a Bearer token.
- Keep internet access available for the Agno documentation page, web search,
  and Yahoo Finance.

Use a development key only for this local example:

```bash
export OS_SECURITY_KEY="replace-with-a-local-secret"
```

## Run

From the repository root:

```bash
.venvs/demo/bin/python -m cookbook.05_agent_os.24_showcase.demo
```

Set `SHOWCASE_PORT` when port 7777 is already in use; otherwise the app uses
port 7777.

Startup performs three observable steps:

1. Insert `https://docs.agno.com/agent-os/introduction.md` into the PostgreSQL
   content table and pgvector table, using `skip_if_exists=True` to avoid a
   duplicate row when the URL-derived content ID is already stored.
2. Query pgvector and require at least one documentation match.
3. Run `AgentOS Documentation Accuracy` with Agno Assist and a Claude judge,
   then store the result before serving port 7777 by default.

The distinct Uvicorn module target is
`cookbook.05_agent_os.24_showcase.demo:app`.

## Authenticate and discover the app

An anonymous request is rejected:

```bash
curl -i http://127.0.0.1:7777/config
```

The root page, `GET /health`, and `GET /info` remain public for discovery and
health checks.

Supply the security key to discover the two Agents and one Team:

```bash
curl \
  -H "Authorization: Bearer ${OS_SECURITY_KEY}" \
  http://127.0.0.1:7777/config
```

The same header is required for runs, sessions, knowledge, traces, and
evaluation endpoints.

## Prompts to try

| Component | Prompt |
|---|---|
| Agno Assist | `Which three component types can AgentOS serve? Link the relevant documentation.` |
| Sage | `Give me current context and market data for NVDA, separating facts from interpretation.` |
| Finance Team | `Compare MSFT and GOOGL fundamentals and recent news in a concise table.` |

Agno Assist is the RAG path: it searches the indexed documentation before
answering. Sage uses `WebSearchTools` for current context and `YFinanceTools`
for market data. The Finance Team delegates to Sage and its market specialist,
then reconciles both member responses.

## Inspect the result

After connecting `http://127.0.0.1:7777` to
[the AgentOS control plane](https://os.agno.com/) with the security key,
inspect:

- **Agents and Teams** for `agno-assist`, `sage`, and `finance-team`.
- **Knowledge** for the `Agno Documentation` instance and indexed introduction.
- **Sessions** after trying the three prompts.
- **Traces** for the Agent, model, tool, and Team spans created by those runs.
- **Evals** for the stored `AgentOS Documentation Accuracy` result.

The equivalent authenticated REST surfaces are `GET /config`,
`GET /knowledge/content`, `GET /sessions`, `GET /traces`, and
`GET /eval-runs`.

## Shutdown

Stop the server with `Ctrl-C`. The PostgreSQL data remains available for the
next run; stop the shared pgvector container only if you started it solely for
this lesson.
