# agnoctl

The CLI for [AgentOS](https://docs.agno.com), built for humans and coding agents.

Create a new AgentOS interactively:

```bash
uvx agno create
```

Choose a starter template and project name, or press Enter to use `agentos-docker`
and `agentos`. The CLI clones the template and copies `example.env` to `.env`.
Add your secrets to `agentos/.env`, then cd into `agentos` and run `agno up`.

For automation, pass the project name and optional template explicitly:

```bash
uvx agno create my-agentos --template agentos-railway --json
```
