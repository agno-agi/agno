# Examples refresh validation

## Use-case companions — September 16

Seven additional starters cover the remaining entries in the documentation's
use-case navigation: Message Routing, Release Agent, Docs Agent, Task Agent,
Feedback Labeler, Analytics Agent, and Account Review. The collection now has
13 examples. Each new directory uses only `requirements.txt` for dependencies,
with Python 3.14 setup instructions; no project manifest, lockfile, or environment
template was added.

| New check | Published Agno 3.0.8 | Local source Agno 3.0.9 |
| --- | --- | --- |
| Fresh Python 3.14.5 per-example requirements installs | 7 passed | Uses those installed dependencies |
| Routing, ownership, page access, SQL and workflow contracts | 11 passed | 11 passed |
| Four AgentOS startup and health checks | 4 passed | 4 passed |
| Five CLI live-model demos | 5 passed | Not repeated |
| Routing live HTTP caller | Passed | Not repeated |
| Release Agent live MCP caller | Passed | Not repeated |

Source checks explicitly selected the framework at
`37fc4121e3cf8863a2957b838fbad7c920bffe0f`. Published live checks used OpenAI
3.14.1 and `gpt-5.6`; Release Agent used FastMCP 4.0.4 and MCP 2.2.0.
Each live run used synthetic inputs and an isolated copy with its own environment
and storage. These are bounded smoke checks, not accuracy or hosted evaluations.

The documentation's introductory Python examples supplied the routing, release,
task, labeling, analytics, and account-review implementations. Changes add
cookbook presentation and demos, rename the task action agent to avoid colliding
with Product Agent, guard the seed script's execution, and clarify the labeling
policy for inputs matching multiple categories. Docs Agent is a new small local
search/read example; it does not claim the full application's published-page
indexing or synchronization.

Live observations: routing selected `billing-support`; task tools completed
Alice's task and rejected access to Bob's; documentation answers read source
pages and acknowledged the missing residency policy; analytics returned $2,000
active MRR and acknowledged the missing cancellation reason; approval paused
before saving the account review. The initial labeling run chose bug for mixed
praise and a bug; the clarified policy produced `needs_review` on rerun. The MCP
client was updated for SDK 2 and successfully called the release tool.

The 11 local contracts exercise queue fallback, task ownership/idempotence,
page-path restrictions, database-enforced write rejection, and workflow
confirmation/rejection. The workflow test replaces only drafting with a fixture
executor. Health checks use real ASGI lifespans. Per-example logs record details.
The repository format/validation scripts and example Ruff checks passed. The
docs checkout remained read-only. No hosted service or production action was run.

## Original six examples: requirements setup — September 16

All six examples now use `requirements.txt` with `uv venv --python 3.14` and
`uv pip install -r requirements.txt`. There are no per-example project manifests,
lockfiles, or environment templates. Test dependencies are installed separately.

Fresh environments used Python 3.14.5, published Agno 3.0.8, OpenAI 3.14.1,
FastMCP 4.0.4 for the brains, and ChromaDB 1.5.9 for Product Agent. Source checks
selected Agno 3.0.9 at the base revision recorded below.

| Current check | Published package | Exact local source |
| --- | --- | --- |
| Six per-example contract suites | 9 passed | 9 passed |
| Two-brain HTTP/MCP suite | 2 passed | 2 passed |
| Six server startups and /health | 6 passed | 6 passed |
| Research/Support offline fixture demos | 2 passed | 2 passed |
| Product live embedding loader, HTTP demo, SSE and restart follow-up | Not run | Passed |

Pip's Python fence and all three demo prompts still match the current first-agent
page; its source-input hash was refreshed. Its README now follows the current
Slack → Railway journey. Product Agent follows the working Agents as API example
with consistent product naming, ChromaDB hybrid retrieval, a local document loader,
SQLite history, and HTTP/SSE calls. Its two tests verify index reopen/update and
real API retrieval/history/reference persistence using deterministic model bounds.
Its separate live smoke used real embeddings and model calls. The older five
agents' live-model results below remain historical, not newly repeated runs.

Formatting and full repository validation were rerun for this change. The docs
checkout was read-only. The removed files eliminate approximately 8,000 lines of
packaging metadata while retaining runtime dependencies and documented commands.

## Original September 10 validation

Validated 2026-09-10 in an isolated worktree on `codex/refresh-agent-examples`.
Base and tested framework source:
`37fc4121e3cf8863a2957b838fbad7c920bffe0f` (Agno **3.0.9**).
The original five examples were tested with published Agno **3.0.8**, Python
3.12.8, OpenAI 3.13.0, and FastMCP 4.0.3 for the two MCP examples. The dependency
setup has since been simplified; see the September 16 results above. Existing shared demo environment was
Agno 3.0.1 and was not silently used as the implementation under test.

## Results

| Check | Published 3.0.8 | Source 3.0.9 |
| --- | --- | --- |
| Personal Agent contracts | 2 passed | 2 passed |
| Second Brain contracts | 2 passed | 2 passed |
| Team Brain contracts | 1 passed | 1 passed |
| Research Agent contracts | 1 passed | 1 passed |
| Support Agent contracts | 1 passed | 1 passed |
| Two-brain HTTP/MCP suite | 2 passed | 2 passed |
| Five AgentOS CLI startups and /health | 5 passed | 5 passed |
| Research and Support offline fixture CLI demos | 2 passed | 2 passed |
| Moved SQL driver/authorizer test | Not run | 1 passed |
| Five bounded live-model demos | Not run | 5 completed |
| Personal/Second/Team separate-process recall | Not run | 3 completed |
| Live-web research demo | Not run | 1 completed |

The seven contracts per implementation cover actual SQLite persistence, note and
learning isolation, explicit learning correction, attribution, retrieval,
references, history and handoff. Scripted model responses exercise the actual
Agent/tool path for Research and Support, but do not evaluate model judgment.
The learning contract uses explicit `forget` then `remember_about`; live Second
Brain additionally exercised model-assisted fact supersession.

HTTP/MCP checks run requests through the full local ASGI authentication stack,
using generated RSA keys and signed JWTs for Alice and Bob. They verify initialize,
tool schemas, invocation, injected identity, rejection of missing/invalid tokens,
unauthorized writes, and rejection of a forged `user_id` argument. Team writes
reach the real FileSystem. The agent's `arun` boundary is stubbed in this transport
suite; separate live-model demos exercise agent behavior. These are local HTTP
checks, not hosted provider or external app integration tests.

## Live observations

- Personal Agent saved the onboarding project, marked sending the draft to Jen
  complete, retained the Friday user test, and recalled the checklist rationale
  from saved files in a fresh session and a separate process.
- Second Brain recorded Alex's profile and preferred update style, learned Harbor
  and Jen, corrected leadership to Maya, and recalled Maya as lead with Jen still
  reviewing. The live fact-supersession judge retired the old lead fact (observed
  confidence 0.98). Separate-process recall retained the correction.
- Team Brain stored two attributed records and the live librarian correctly
  recalled Alice's checklist decision and Bob's Friday user test with reasoning.
  A new process recalled the same log.
- Research with a live model over fictional fixtures read both sources and saved
  a cited brief that described the conflicting frequency recommendations.
- Support answered the exports question with documentation, understood the member
  follow-up, then acknowledged that the documentation could not establish a
  Germany contractual guarantee. It saved a structured local handoff.
- One additional live-web research run completed with six findings citing three
  successfully inspected pages: Share Oxford's repair cafe FAQ, the Welsh
  Government's repair/reuse evaluation summary, and Miller Research's evaluation
  project page. Some candidate pages returned HTTP 403; the agent found accessible
  alternatives and did not cite the failed pages. The artifact's cited URLs all
  belonged to its inspected-source set. This smoke does not establish general
  search reliability or entailment of every claim by its citation.

All live checks used the existing local test API key, isolated temporary databases,
and bounded runs. No user databases, real support tickets, external accounts,
deployments, releases, pushes, or PRs were created.

## Reproduce with the current requirements setup

From any example directory:

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install pytest pytest-asyncio
python -m pytest test_contracts.py -q
PYTHONPATH=../../../libs/agno python -m pytest test_contracts.py -q
```

From `cookbook/examples/team_brain`, also run:

```bash
python -m pytest ../test_mcp.py -q
PYTHONPATH=../../../libs/agno python -m pytest ../test_mcp.py -q
```

The original September 10 CLI checks used the former per-example project setup.
Their outcomes are historical; the Python 3.14 requirements checks are recorded
separately above.

Repository gates:

- `./scripts/format.sh`: passed. Its unrelated pre-existing Elasticsearch test
  formatting change was removed from this worktree to preserve the requested scope.
- `./scripts/validate.sh`: passed, including Ruff, mypy (1,053 Agno and 21 agnoctl
  source files), and the repository's quickstart pattern check (13 files, zero
  violations). It passed again after removing that unrelated formatting change.
- Changed Python Ruff checks, relative Markdown links, stale Metrics Desk/`test.py`
  instructions, tutorial SHA-256 parity, and `git diff --check`: passed.

The standalone tutorial file intentionally keeps the source's exact formatting and
has no added cookbook banners/docstring. Tests and fixture models are supporting
files rather than runnable cookbook lessons.

## Scope and remaining limits

The six directories now contain main agents, demos, README/TEST_LOG files,
requirements.txt files, and focused contracts. Product Agent adds a document
loader and fictional sample product documentation. Research adds
fictional sources and a scripted model; Support adds fictional Markdown product
docs and a scripted model. Shared code exists only in the HTTP test harness; there
is no shared application framework.

Metrics Desk moved to `cookbook/91_tools/sql_read_only` with its useful read-only
SQLite implementation and historical logs. Its CLI driver is now `demo.py`; the
tools index links to it. Driver safety was rechecked; its live-model demo was not
rerun. Privacy wording now acknowledges that SQL results reach the model provider.

No hosted integration, production Postgres, Slack, OAuth issuer, Control Plane,
or external MCP app was tested. JWT servers require a trusted issuer; local demo
identities are not authentication. Small lexical support retrieval can miss
paraphrases. Fixture tests prove contracts, not model accuracy. No framework
changes or owner decisions are required for this local refresh.
