# 09_coding_engineers

Workflows whose steps are coding engineers: `ClaudeAgent` and `CodexAgent`, each working in its own Docker sandbox on a checkout of your repository.

## Examples

- `pr_to_merge_ready.py`: takes a GitHub pull request URL through review rounds until nothing real is left to fix.

## pr_to_merge_ready.py

The procedure, as steps you can read and change:

1. **Read pull request** reads the title, description, head commit and diff from GitHub, once.
2. **Review rounds**, a `Loop` of at most three:
   - **Independent reviews**, a `Parallel`: a Claude engineer and a Codex engineer review the pull request at the same time. Neither sees the other's review. Each has the pull request's code checked out in its own sandbox and can run things.
   - **Triage**: an agent keeps only the points that are real problems a user would hit, and says why it dropped the rest. No nitpicks.
   - If triage kept nothing, the loop ends: the pull request is merge-ready.
   - **Fix what triage kept**, a `Condition`: one engineer fixes the kept points in its own sandbox checkout and prints its change as a diff. The next round's reviewers apply that diff and review the result.
3. **Report**: the result first, then what triage kept and dropped in each round, the fix as a diff, and every review in full.

Nothing is pushed and nothing is posted to GitHub. The sandboxes are given no GitHub token, so an engineer can read a public repository and cannot write to it.

The small function steps (`review_brief`, `triage_brief`, `fix_brief`, `record_triage`, `record_fix`) exist because an agent step is sent only the previous step's output. They build what each agent is asked and keep each round's results in the workflow's session state for the report.

## Prerequisites

- Docker, and the sandbox runtime image:
  ```bash
  .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
  ```
- PostgreSQL: `./cookbook/scripts/run_pgvector.sh`
- `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`. They are passed into the sandboxes, so use keys with a low spending limit.
- Optional: `GITHUB_READ_TOKEN`, a read-only token, raises GitHub's rate limit for reading the pull request on the host. It is not passed to the sandboxes.

## Run

```bash
.venvs/demo/bin/python cookbook/04_workflows/09_coding_engineers/pr_to_merge_ready.py https://github.com/agno-agi/agno/pull/11950
```

## Settings

| Environment variable | Default | What it sets |
|---|---|---|
| `REVIEW_REPOSITORY_URL` | `https://github.com/agno-agi/agno` | The repository the engineers check out. Only its pull requests are accepted. |
| `REVIEW_REPOSITORY_BRANCH` | `main` | The branch the sandboxes start from before fetching the pull request. |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | Model of the Claude reviewer and the fixing engineer. |
| `CODEX_MODEL` | `gpt-5.6-luna` | Model of the Codex reviewer. |
| `TRIAGE_MODEL` | `gpt-5.6-luna` | Model of the triage agent. |
| `AGNO_SANDBOX_IMAGE` | `agno-sandbox:local` | The sandbox image. |
| `AGNO_SANDBOX_DB_URL` | local pgvector | The database for sessions and runs. |

## Limits to know

- A private repository needs a read-only token inside the sandboxes (`DockerSandbox(env={"GITHUB_READ_TOKEN": ...})`). Never pass a token that can push.
- The fix is reported as the diff the fixing engineer printed. It is not read from the sandbox's saved checkout.
- The engineers can run tests only if the sandbox image has the project's test dependencies. The stock image does not have `pytest`.
- Each engineer keeps one checkout and one conversation per workflow session, so later rounds continue where the earlier one stopped.
- Serve the workflow from AgentOS as code (`AgentOS(workflows=[workflow])`). A workflow stored through Studio cannot use a Claude or Codex engineer as a step.
