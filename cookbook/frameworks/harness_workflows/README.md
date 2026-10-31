# Harness agents as workflow steps

Claude Code (`ClaudeAgent`) and Codex (`CodexAgent`) can run as steps of an Agno `Workflow`, next to
native Agno agents and teams. Use one as a step's agent, or list it directly in `steps`, `Parallel`,
`Loop`, `Condition` or `Router`, as you would an Agno agent.

```python
from agno.agents.claude import ClaudeAgent
from agno.workflow import Parallel, Step, Workflow

engineer = ClaudeAgent(id="claude-engineer", name="Claude Engineer", cwd="/path/to/project", db=db)
workflow = Workflow(
    steps=[Step(name="build", agent=engineer), Parallel(claude_reviewer, codex_reviewer), Step(name="summary", agent=writer)],
    db=db,
)
workflow.run("Add a test for the 100 dollar boundary", session_id="build")
```

## Cookbooks

| Cookbook | What it shows |
|---|---|
| [`claude_step.py`](claude_step.py) | Claude Code writes and runs a test, then an Agno agent summarises; a second run of the session asks Claude about the file it wrote, and it answers from its own conversation. |
| [`parallel_review.py`](parallel_review.py) | Claude Code and Codex review the same code in a `Parallel`, each in its own conversation, and an Agno agent merges the reviews. |
| [`loop_until_green.py`](loop_until_green.py) | A `Loop` runs Claude Code until it reports that the tests pass. |
| [`router_step.py`](router_step.py) | A `Router` sends change requests to Claude Code and questions to Codex. |
| [`sandboxed_step.py`](sandboxed_step.py) | Claude Code in its own Docker container as a step: across two runs of a session it writes a file, then edits the same file on its computer. |
| [`workflow_agentos.py`](workflow_agentos.py) | A build, review and summary workflow behind AgentOS. The workflow page shows each step's agent, and the harness agents are also served on their own. |

```bash
export OPENAI_API_KEY=...          # Codex and the Agno steps
export CLAUDE_CODE_OAUTH_TOKEN=... # or ANTHROPIC_API_KEY, for Claude Code
.venvs/demo/bin/python cookbook/frameworks/harness_workflows/claude_step.py
```

Each cookbook works on a temporary copy of the [sample project](../sample_project/README.md), since Claude edits files there. The sandboxed cookbook also needs the runtime image and Postgres (see its docstring and the [sandbox README](../sandbox/README.md)).

## How a harness step works

- **Sessions.** A workflow runs every step under the workflow's session id, and that session row belongs to the workflow. A harness step keeps its native conversation (the Claude session id, the Codex thread id) in a session of its own named `<workflow session id>:<agent id>`, so the workflow's session is never overwritten and two different harness agents never share a conversation. The workflow stores the step's run with its other step runs, as it does for an Agno agent.
- **Continuity.** One harness agent keeps one conversation per workflow session. A later run of the same session, a later `Loop` iteration, or another step that uses the same agent resumes it, so the agent can refer to its earlier work. Use a separate agent, with its own id, for a step that should start fresh.
- **Parallel.** A conversation takes one turn at a time, so the same harness agent cannot run in two branches of a `Parallel`; the workflow refuses it when it is built.
- **Standalone runs.** The workflow passes its id on each step call instead of storing it on the agent. The same agent instance can also run on its own, for example when AgentOS serves it directly, and those runs are saved in their own sessions.
- **Sandboxed steps.** A step agent with `sandbox=` runs every turn in its own computer. Its computer binding, checkpoints and native conversation live in its own step session, and files it writes carry over to its next turn. The step session's metadata links it back to the workflow (`workflow_id`), as it does for a step without a sandbox. AgentOS applies its startup checks (Postgres, a checkpoint store every replica can read under a durable queue) to sandboxed harness agents in served workflows, at any depth, including members of a team used as a step.
- **Native-only settings.** Workflow settings that only apply to Agno agents, such as storage flags, have no effect on a harness step.

## Not yet supported

- Workflows saved as Studio components cannot reference a harness agent as a step yet.
- A harness step does not receive the workflow's run metadata; Agno agents read it from the run context, which harness agents ignore.
