# Agno Demo

A demo AgentOS running wiki agents. Ingest URLs, images, voice memos, or PDFs; digest it; file a clean, linked page — across three backends: **local markdown, a git repo, or Notion**. Built on AgentOS with SQLite sessions + memory, small enough to fork.

> For a production version of this demo, see the [agent-platform-railway](https://github.com/agno-agi/agent-platform-railway) codebase.

## Agents

| Agent | What it does | Backing |
|-------|--------------|---------|
| **LocalWiki** | Read + write a markdown wiki. Ingest a URL *or* attached media (image, audio, video, PDF) — it digests and files a page in one call. | `WikiContextProvider(FileSystemBackend, web=ParallelMCPBackend)` |
| **GitWiki** *(env-gated)* | The same agent, but the wiki is a real git repo — auto-commits and pushes after each write. Registered when `WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN` are set. | `WikiContextProvider(GitBackend, …)` |
| **NotionWiki** *(env-gated)* | The same agent, but the wiki is a Notion database (one row per page); the database is the source of truth your team opens in Notion. Registered when `NOTION_API_KEY` + `NOTION_DATABASE_ID` are set. | `WikiContextProvider(NotionDatabaseBackend, …)` |
| **CodeSearch** | A different kind of agent, left in as an example — answers questions about this repository (file paths, line numbers). | `WorkspaceContextProvider` |

Every agent runs on **Gemini 3.5 Flash** (see `settings.py`), so every agent is multimodal — the wiki agents read whatever you attach. All share `db=get_db()` (SQLite at `data/demo.db`), agentic memory, datetime + history in context, and markdown output.

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
export GOOGLE_API_KEY="..."      # required — every agent runs on Gemini 3.5 Flash

export PARALLEL_API_KEY="..."    # optional — raises the rate ceiling on the keyless Parallel MCP web ingest

# Optional — enables the GitWiki agent
export WIKI_REPO_URL="https://github.com/<owner>/<repo>.git"
export WIKI_GITHUB_TOKEN="ghp_..."       # PAT with contents:write

# Optional — enables the NotionWiki agent
export NOTION_API_KEY="ntn_..."          # integration token
export NOTION_DATABASE_ID="..."          # UUID from the database URL
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

- **Ingest a URL** — LocalWiki: *"Add https://docs.agno.com/ to the wiki."* It fetches, digests, and files a page.
- **Ingest media** — attach `assets/sample-diagram.png` (or your own image / voice memo) to LocalWiki: *"Digest this and file it under notes/."*
- **Ask the wiki** — *"What's in the wiki?"* or *"What does the wiki say about X?"*
- **Code Q&A** — CodeSearch: *"Which agents are registered in this demo?"*

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

Each case runs one agent once, then checks the response with `AgentAsJudgeEval` (LLM rubric, binary pass/fail) and optionally `ReliabilityEval` (tool-call assertion). Results log to SQLite — connect AgentOS at os.agno.com to see history.

## Extending

To add an agent: drop a file in `agents/`, register it in `run.py`'s `AgentOS(agents=[...])` list, add quick prompts to `config.yaml`, restart. Add eval cases in `evals/cases.py` once it's stable.

## Regenerating requirements

```bash
./cookbook/01_demo/generate_requirements.sh
```

Edits to `requirements.in` are the source of truth; the `.txt` is regenerated and pinned via `uv pip compile`.
