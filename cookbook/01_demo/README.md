# Agno Demo

An AgentOS you can copy and build on: a multimodal knowledge base. Wiki agents (local, git, Notion), keyless web research, Gemini multimodal ingest, a verified multi-model swarm, and a research pipeline — all on AgentOS with SQLite sessions + memory, plus an optional Slack interface.

For a production-ready version of this demo, see the [agent-platform-railway](https://github.com/agno-agi/agent-platform-railway) codebase. Comes with AgentOS (FastAPI) + Postgres. One-command deploy to Railway. JWT auth, Slack integration, eval suite, and recursive-improvement loops driven by Claude Code.

## Agents

| Agent | What it does | Backing |
|-------|--------------|---------|
| **LocalWiki** | Read + write a local markdown wiki. Ingest URLs via the web — "add a page about X" fetches, digests, and files in one update call. | `WikiContextProvider(FileSystemBackend, web=ParallelMCPBackend)` |
| **GitWiki** *(env-gated)* | Same as LocalWiki, but the wiki lives in a real git repo. Auto-commits and pushes after each write. Registered when `WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN` are set. | `WikiContextProvider(GitBackend, web=ParallelMCPBackend)` |
| **NotionWiki** *(env-gated)* | Same as LocalWiki, but the wiki is a Notion database (one row per page). Writes round-trip through Notion blocks; the database is the source of truth. Registered when `NOTION_API_KEY` + `NOTION_DATABASE_ID` are set. | `WikiContextProvider(NotionDatabaseBackend, web=ParallelMCPBackend)` |
| **MediaIngest** *(env-gated)* | Multimodal ingest with Gemini 3.5 Flash. Drop an image, voice memo, video, or PDF — it digests the media into structured markdown, fills gaps with cited web research, and files a page. Writes to Notion when configured, else the local wiki. Registered when `GOOGLE_API_KEY` is set. Sample media in `assets/`. | `Gemini(gemini-3.5-flash)` + wiki + web providers |
| **WebSearch** | Keyless web research via Parallel MCP. Returns answers with cited URLs. | `WebContextProvider(ParallelMCPBackend)` |
| **CodeSearch** | Answers questions about this repository — file paths, line numbers. | `WorkspaceContextProvider` |
| **Researcher** | Composes WebSearch + LocalWiki + CodeSearch on one agent. Checks the wiki first, searches the web, queries the codebase, and files findings back into the wiki. | composition of the three providers above |

All agents share `db=get_db()` (SQLite at `data/demo.db`), agentic memory on, datetime + history in context, markdown output.

## Teams

| Team | What it does | Pattern |
|------|--------------|---------|
| **Swarm** | A verified k-model ensemble. Broadcast the same question to web-search proposers on different providers (OpenAI, Anthropic, and Google when `GOOGLE_API_KEY` is set), then a Verifier re-checks each claim against its cited sources before the leader synthesizes — flagging unsupported citations and giving a confidence read based on model agreement AND verification. | `Team(mode=broadcast, members=[proposers], tools=[verify_claims])` |

This is the "assemble agents on a common problem, mix providers — but verify before you trust" pattern. The proposers and the Verifier share one Parallel MCP session; the Verifier catches confident-but-wrong citations that a plain k-LLM vote would average in.

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

# Optional — enables the MediaIngest agent (Gemini 3.5 Flash multimodal)
export GOOGLE_API_KEY="..."

# Optional — enables the GitWiki agent
export WIKI_REPO_URL="https://github.com/<owner>/<repo>.git"
export WIKI_GITHUB_TOKEN="ghp_..."   # PAT with contents:write

# Optional — enables the NotionWiki agent (and where MediaIngest files to)
export NOTION_API_KEY="ntn_..."          # integration token
export NOTION_DATABASE_ID="..."          # UUID from the database URL

# Optional — enables the Slack interface (see "Slack" below)
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_SIGNING_SECRET="..."
```

### 4. Serve

```bash
fastapi dev cookbook/01_demo/run.py
```

Then open [os.agno.com](https://os.agno.com) and sign in:

1. **Add OS** → **Local**
2. Connect to `http://localhost:8000`, call it Local AgentOS
3. Chat with your agents

## Try it

A few prompts that show what the demo can do:

- **Multimodal ingest** — attach a whiteboard photo, screenshot, or voice memo to **MediaIngest**: *"Digest this and file it to the wiki."* It turns the media into a structured, cited page.
- **Verified swarm** — ask **Swarm** a contested factual question: *"What's the latest stable CPython release? Cite sources."* It proposes across OpenAI / Anthropic / Google, verifies each citation, then synthesizes with a confidence read.
- **Research and file** — ask the **Researcher**: *"Research the CPython release cycle — check the wiki first, then the web — and file a summary under papers/."*
- **Morning brief** — run the **Brief** workflow: *"Brief me on Agno's AgentOS. File it under briefs/."*

## Slack (optional)

Expose the demo in Slack via the AgentOS Slack interface. With `SLACK_BOT_TOKEN`
and `SLACK_SIGNING_SECRET` set, `run.py` wires Slack to the **MediaIngest** agent
(or the Researcher when Gemini isn't configured) — drop a photo or voice memo in
Slack and it lands in your wiki.

Local dev with ngrok:

1. Serve the app (`fastapi dev cookbook/01_demo/run.py`) — it listens on port 8000.
2. `ngrok http 8000` and copy the `https://` URL.
3. In your Slack app's **Event Subscriptions**, set the Request URL to
   `https://<ngrok>/slack/events` and subscribe to the `app_mention` and
   `message.im` bot events.
4. Install the app to your workspace, then DM it a file or @mention it in a channel.

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
