# Harness agents as team members

Claude Code (`ClaudeAgent`) and Codex (`CodexAgent`) can be members of an Agno `Team`, next to
native Agno agents. The leader is a normal Agno model that decides what to delegate; each harness
does its share with its own model, tools and workspace; the team collects every member's run as it
does for any member.

```python
from agno.agents.claude import ClaudeAgent
from agno.models.openai import OpenAIResponses
from agno.team import Team

engineer = ClaudeAgent(id="claude-engineer", name="Claude Engineer", role="Writes and runs code", cwd="/path/to/project", db=db)
team = Team(model=OpenAIResponses(id="gpt-5.6-luna"), members=[engineer, writer], add_history_to_context=True, db=db)
team.run("Add a test for the 100 dollar boundary and run it", session_id="review")
```

## Cookbooks

| Cookbook | What it shows |
|---|---|
| [`claude_member.py`](claude_member.py) | Claude Code writes and runs a test for the leader; a second turn asks it about the file it made, and it answers from its own conversation. |
| [`codex_member.py`](codex_member.py) | Codex reviews the project read-only; a follow-up turn goes back to Codex, which continues the same thread. |
| [`mixed_team.py`](mixed_team.py) | Claude Code writes, Codex reviews and an Agno agent summarises, in one team run. |
| [`team_agentos.py`](team_agentos.py) | A Claude Code, Codex and Agno team behind AgentOS, self-contained: the team page lists both harness members, and the leader involves only the members a request needs. |
| [`sandboxed_member.py`](sandboxed_member.py) | Claude Code in its own Docker container as a team member: across two team turns it writes a file, then edits the same file on its computer. |
| [`sandboxed_team_agentos.py`](sandboxed_team_agentos.py) | That team behind AgentOS with a durable queue on Postgres: a background team run is a queued job, and the leader delegates to the sandboxed member inside it. |

```bash
export OPENAI_API_KEY=...          # leader, Codex and the Agno writer
export CLAUDE_CODE_OAUTH_TOKEN=... # or ANTHROPIC_API_KEY, for Claude Code
.venvs/demo/bin/python cookbook/frameworks/harness_teams/claude_member.py
```

The Claude cookbooks work on a temporary copy of the [sample project](../sample_project/README.md), since Claude edits files there; Codex reads the project in place, read-only. The sandboxed cookbooks also need the runtime image and Postgres (see their docstrings and the [sandbox README](../sandbox/README.md)).

## How membership works

- **Sessions.** A team runs every member under the team's session id, and that session row belongs to the team. A harness member keeps its native conversation (the Claude session id, the Codex thread id) in a session of its own named `<team session id>:<member id>`, so two harness members of one team never share a conversation and the team's session is never overwritten. The member's runs are stored by the team, in the team session, like any other member's.
- **Continuity.** A later turn of the same team session resumes the member's own conversation, so a follow-up delegated to the same member can refer to its earlier work. Give the leader `add_history_to_context=True` so it remembers earlier turns too; without it the leader may answer a follow-up itself.
- **Input.** The leader delegates a task as text. With `determine_input_for_members=False` the team forwards its own input instead; a `Message` or a list of messages is turned into text, since the harnesses take text.
- **Sandboxed members.** A member with `sandbox=` runs every delegated turn in its own computer. Its computer binding, checkpoints and native conversation live in its own member session, so the team's session is never bound to one member's computer and two sandboxed members of a team each get their own; files the member writes carry over to its next turn, on a warm computer or one restored from its checkpoint. The sandbox records each turn as a run of the member session under its own id, `<member run id>.sandbox`; the team stores the member's result in the team session under the id it assigned, with a pointer to the sandbox's run in `metadata.sandbox.run_id`. Cancelling the team run cancels the member's sandbox turn and releases its session. A sandboxed member takes the same run options a served sandboxed agent does; the native-only options a team hands its members are not forwarded. AgentOS applies its startup checks (Postgres, a checkpoint store every replica can read under a durable queue) to sandboxed members of served teams at any depth.
- **Member settings.** `role` and `description` are shown to the leader. Team settings that only apply to native agents, such as knowledge filters and `send_media_to_model`, are accepted and have no effect on a harness member.

## Not yet supported

- Saving a team with harness members as a Studio component: the harness members are not serialized.
- If a member's native conversation cannot be resumed, for example on another machine without Claude's database-backed transcript store, it starts a new conversation without the team history; the leader still passes the context it chooses in the task.
