# Agno Demo

A minimal AgentOS to copy and build on. A small set of agents and a local SQLite database for sessions + memory.

For a production-ready version of this demo, see the [agent-platform-railway](https://github.com/agno-agi/agent-platform-railway) codebase. Comes with AgentOS (FastAPI) + Postgres. One-command deploy to Railway. JWT auth, Slack integration, eval suite, and recursive-improvement loops driven by Claude Code.

## Agents

| Agent | What it does | Backing |
|-------|--------------|---------|
| **LocalWiki** | Read + write a local markdown wiki. Ingest URLs via the web — "add a page about X" fetches, digests, and files in one update call. | `WikiContextProvider(FileSystemBackend, web=ParallelMCPBackend)` |
| **GitWiki** *(env-gated)* | Same as LocalWiki, but the wiki lives in a real git repo. Auto-commits and pushes after each write. Registered when `WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN` are set. | `WikiContextProvider(GitBackend, web=ParallelMCPBackend)` |
| **WebSearch** | Keyless web research via Parallel MCP. Returns answers with cited URLs. | `WebContextProvider(ParallelMCPBackend)` |
| **CodeSearch** | Answers questions about this repository — file paths, line numbers. | `WorkspaceContextProvider` |
| **Researcher** | Composes WebSearch + LocalWiki + CodeSearch on one agent. Checks the wiki first, searches the web, queries the codebase, and files findings back into the wiki. | composition of the three providers above |

All agents share `db=get_db()` (SQLite at `data/demo.db`), agentic memory on, datetime + history in context, markdown output.

## Teams

| Team | What it does | Pattern |
|------|--------------|---------|
| **Swarm** | Broadcast the same question to two web-search agents — one on OpenAI gpt-5.5, one on Anthropic claude-opus-4-7 — and synthesize. Lead calls out where the models agree, disagree, and a confidence read. | `Team(mode=broadcast, members=[openai_agent, anthropic_agent])` |

This is the "assemble a bunch of agents on a common problem, mix OpenAI and Anthropic" pattern. Both members share the same web provider — one Parallel MCP session, two perspectives.

## Get started

### 1. Create a virtual environment

```bash
uv venv .venvs/demo --python 3.12
source .venvs/demo/bin/activate
```

### 2. Install dependencies

```bash
uv pip install -r cookbook/01_demo/requirements.txt
```

### 3. Set your API keys

```bash
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."   # required for the Swarm team's Claude member

export PARALLEL_API_KEY="..."    # optional — raises rate ceiling on Parallel MCP

# Optional — enables the GitWiki agent
export WIKI_REPO_URL="https://github.com/<owner>/<repo>.git"
export WIKI_GITHUB_TOKEN="ghp_..."   # PAT with contents:write
```

### 4. Serve

```bash
fastapi dev cookbook/01_demo/run.py
```

Then open [os.agno.com](https://os.agno.com) and sign in:

1. **Add OS** → **Local**
2. Connect to `http://localhost:8000`, call it Local AgentOS
3. Chat with your agents

## Evals

From the repo root:

```bash
python -m cookbook.01_demo.evals               # run all cases (concise)
python -m cookbook.01_demo.evals -v            # stream the full agent run
python -m cookbook.01_demo.evals --case <name> # run one case
```

Or from `cookbook/01_demo`:

```bash
python -m evals
python -m evals -v
python -m evals --case <name>
```

Each case runs the agent (or team / workflow) once, then checks the response with `AgentAsJudgeEval` (LLM rubric, binary pass/fail) and optionally `ReliabilityEval` (tool-call assertion). Results log to SQLite — connect AgentOS at os.agno.com to see history.

## Extending

To add an agent: drop a file in `agents/`, register it in `run.py`'s `AgentOS(agents=[...])` list, add quick prompts to `config.yaml`, restart. Same pattern for `teams/` and `workflows/`. Add eval cases in `evals/cases.py` once it's stable.

## Regenerating requirements

```bash
./cookbook/01_demo/generate_requirements.sh
```

Edits to `requirements.in` are the source of truth; the `.txt` is regenerated and pinned via `uv pip compile`.
