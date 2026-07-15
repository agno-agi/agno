# agnoctl

The CLI for [AgentOS](https://docs.agno.com), built for humans and coding agents.

Create a new AgentOS interactively:

```bash
uvx agno create
```

Choose from nine maintained starters—Docker, AWS, Azure, Fly, GCP, Helm, Modal,
Railway, and Render—and name your project. Press Enter to use `agentos-docker`
and `agentos`. The CLI clones the template and copies `example.env` to `.env`.
Add your secrets to `agentos/.env`, then cd into `agentos` and run `agno up`.

For automation, pass the project name and optional template explicitly:

```bash
uvx agno create my-agentos --template agentos-railway --json
```
