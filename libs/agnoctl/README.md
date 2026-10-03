# agnoctl

The CLI for [AgentOS](https://docs.agno.com), built for humans and coding agents.

Create a new AgentOS interactively:

```bash
uvx agno create
```

Choose from nine maintained starters—Docker, AWS, Azure, Fly, GCP, Helm, Modal,
Railway, and Render—using the arrow keys or `1`–`9`, then name your project.
Press Enter to use `agentos-docker` and `agent-platform`. The CLI clones the
template and copies `example.env` to `.env`.

Then enter the project and choose a setup path:

```bash
cd agent-platform
```

Recommended: open the project in your coding agent and ask it to **run the
`setup-platform` skill in `.agents/skills/`**. The skill configures the project,
starts it, verifies it, connects the AgentOS UI, and helps build your first agent.

Or set it up manually: add your secrets to `.env`, then run:

```bash
uvx agno up
```

For automation, pass the project name and optional template explicitly:

```bash
uvx agno create my-agentos --template agentos-railway --json
```
