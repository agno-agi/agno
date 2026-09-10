# Examples refresh validation

Validated 2026-09-10 in an isolated worktree on `codex/refresh-agent-examples`.
Base and tested framework source:
`37fc4121e3cf8863a2957b838fbad7c920bffe0f` (Agno **3.0.9**).
Each standalone project declares and locks published Agno **3.0.8**. Tests used
Python 3.12.8; lockfiles record every transitive version (including OpenAI 3.13.0
and FastMCP 4.0.3 for the two MCP examples). Existing shared demo environment was
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

## Reproduce

From any example directory, `uv sync --locked` creates its isolated environment.
The README commands export credentials explicitly; `.env.example` is not loaded.
Published contract tests:

```bash
uv run --no-sync pytest test_contracts.py -q
```

Source contract tests, from that same directory in a checkout:

```bash
PYTHONPATH=../../../libs/agno uv run --no-sync pytest test_contracts.py -q
```

From `cookbook/examples/team_brain`, the two-brain HTTP/MCP suite:

```bash
uv run --no-sync pytest ../test_mcp.py -q
PYTHONPATH=../../../libs/agno uv run --no-sync pytest ../test_mcp.py -q
```

Clean-command checks copied each example's tracked inputs into a new temporary
directory and reused its freshly installed isolated environment through
`UV_PROJECT_ENVIRONMENT`. They ran `uv run --no-sync <example>.py`, verified
`/health` on a temporary loopback port via `AGENT_OS_PORT`, and stopped every
server. Research and Support also ran `uv run --no-sync demo.py --fixture` there.
Serving the two brains used generated test RSA verification keys. The five live
model demos used each project's environment and exact local source; the three
brain restart checks ran `demo.py --recall-only` in their existing test data
directories. The additional research run used `RESEARCH_MODE=live`.

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

The five directories contain main agents, demos, README/TEST_LOG files, independent
pyproject/lock files, environment templates, and focused contracts. Research adds
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
