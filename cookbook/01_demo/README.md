# Agno Demo

A demo AgentOS running multiple wiki agents. Ingest URLs, images, voice memos, or PDFs. Store them as clean, linked pages across three backends: local markdown files, a git repo, or Notion.

Built on AgentOS with SQLite-backed sessions. The codebase is small enough to grok in an afternoon, and stable enough to build on.

> For a production version of this demo, see the [agent-platform-railway](https://github.com/agno-agi/agent-platform-railway) codebase.

## Agents

| Agent | What it does |
|-------|--------------|
| **LocalWiki** | Reads and writes a markdown wiki. Ingest a URL, an attached image, or a PDF. It digests and files a page in one call. |
| **GitWiki** *(env-gated)* | The same agent with the wiki stored as a git repo. It auto-commits and pushes after each write. Registered when `WIKI_REPO_URL` and `WIKI_GITHUB_TOKEN` are set. |
| **NotionWiki** *(env-gated)* | The same agent with the wiki stored as a Notion database, one row per page. The database is the source of truth your team opens in Notion. Registered when `NOTION_API_KEY` and `NOTION_DATABASE_ID` are set. |
| **CodeSearch** | Answers questions about this repository, with file paths and line numbers. |

The three wiki agents can also produce downloadable HTML files. Agents run on **gpt-5.5** by default, and you can use any model (see `settings.py`).

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
export OPENAI_API_KEY="..."      # required: default model is gpt-5.5

export PARALLEL_API_KEY="..."    # optional: raises limits on the keyless Parallel MCP

export GOOGLE_API_KEY="..."      # optional: for gemini audio and video
```

GitWiki and NotionWiki each switch on when their backend credentials are set. See "Enable the other wiki backends" below.

### 4. Serve

```bash
fastapi dev cookbook/01_demo/run.py
```

Then open [os.agno.com](https://os.agno.com) and sign in:

1. **Add OS** → **Local**
2. Connect to `http://localhost:8000`, call it Local AgentOS
3. Chat with your agents

## Enable the other wiki backends

LocalWiki and CodeSearch run with just `OPENAI_API_KEY`. GitWiki and NotionWiki are the same wiki agent pointed at a different backend, and each registers once its credentials are set.

### GitWiki: a wiki in a GitHub repo

The wiki lives in a git repo. Every write is auto-committed and pushed.

1. **Pick a repo** to hold the wiki. A fresh, empty repo is fine. Create it with an initial commit (tick *"Add a README"* on GitHub) so the `main` branch exists for the first clone.
2. **Create a token** with write access to that repo:
   - *Fine-grained PAT (recommended):* GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → **Generate new token**. Scope it to the one repo and set **Repository permissions → Contents → Read and write**.
   - *Classic PAT:* use the `repo` scope.
3. **Export and restart:**
   ```bash
   export WIKI_REPO_URL="https://github.com/<owner>/<repo>.git"  # HTTPS, not SSH
   export WIKI_GITHUB_TOKEN="github_pat_..."                     # contents: read and write
   export WIKI_BRANCH="main"                                     # optional, default: main
   ```

The URL must be HTTPS. SSH `git@…` URLs are rejected. The token is embedded for auth and scrubbed from logs. The clone is stored under `data/git-wiki/` (gitignored).

### NotionWiki: a wiki in a Notion database

The wiki is a Notion database, one row per page, that your team opens in Notion. The agent files markdown, and Notion stays the source of truth.

1. **Create an integration** at [notion.so/profile/integrations](https://www.notion.so/profile/integrations) → **New integration** → *Internal*. Copy its token (`ntn_…`). The default read, insert, and update content capabilities are all it needs.
2. **Create a database** for the wiki. Use a full-page database; table view is fine. The only column it needs is the built-in **title**, and the agent names each page. The wiki is flat: one row per page, no nested pages.
3. **Connect the integration to the database.** This step is easy to miss. Open the database as a full page → **•••** menu → **Connections** → add your integration. Without it, the API cannot see the database.
4. **Copy the database ID** from its URL. It's the 32-character hex in the path, before the `?v=` (the `v=` value is the view, so leave it out):
   ```
   https://www.notion.so/<workspace>/<DATABASE_ID>?v=<view_id>
   ```
5. **Export and restart:**
   ```bash
   export NOTION_API_KEY="ntn_..."
   export NOTION_DATABASE_ID="<32-char hex from the URL>"
   ```

The local mirror lands under `data/notion-wiki/` (gitignored). On startup the backend rebuilds the mirror from Notion, so the database is always the source of truth.

## Try it

- **Ingest a URL** with LocalWiki: *"Read docs.agno.com and file a tight summary under guides/."* It fetches, digests, and hands you the digest — not just a "done."
- **Ingest media** by attaching `evals/assets/sample-diagram.png` (or your own image or PDF) to LocalWiki: *"Digest this diagram into a page under notes/."* It reads the image itself and files the markdown.
- **Generate HTML** with LocalWiki: *"Generate a standalone HTML landing page for a coffee shop, 'Bean There'."* You get a downloadable `.html` file.
- **See the backend** with GitWiki or NotionWiki: *"Draft a deploy runbook and push it"* lands a real commit; *"File a call summary for Acme Corp"* shows up as a Notion page your team opens.
- **Code Q&A** with CodeSearch: *"Where is generate_html_file wired into the wiki agents?"* — answered with `file:line` citations.

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

Each case runs one agent once, then checks the response with `AgentAsJudgeEval` (an LLM rubric with a binary pass or fail) and optionally `ReliabilityEval` (a tool-call assertion). Results log to SQLite. Connect AgentOS at os.agno.com to see history.

## Extending

To add an agent: drop a file in `agents/`, register it in the `AgentOS(agents=[...])` list in `run.py`, add quick prompts to `config.yaml`, and restart. Add eval cases in `evals/cases.py` once it's stable.

## Regenerating requirements

```bash
./cookbook/01_demo/generate_requirements.sh
```

Edits to `requirements.in` are the source of truth. The `.txt` is regenerated and pinned with `uv pip compile`.
