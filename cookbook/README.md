# Agno Cookbooks

Hundreds of examples. Copy, paste, run.

## Where to Start

**New to Agno?** Start with [00_quickstart](./00_quickstart) — it walks you through the fundamentals, with each cookbook building on the last.

**Want to see something real?** Jump to [01_demo](./01_demo) — advanced use cases. Run the examples, break them, learn from them.

**Want to explore a particular topic?** Find your use case below.

---

## Build by Use Case

### I want to build a single agent
[02_agents](./02_agents) — The atomic unit of Agno. Start here for tools, RAG, structured outputs, multimodal, guardrails, and more.

### I want agents working together
[03_teams](./03_teams) — Coordinate multiple agents. Async flows, shared memory, distributed RAG, reasoning patterns.

### I want to orchestrate complex processes
[04_workflows](./04_workflows) — Chain agents, teams, and functions into automated pipelines.

### I want to deploy and manage agents
[05_agent_os](./05_agent_os) — Deploy to web APIs, Slack, WhatsApp, and more. The control plane for your agent systems.

---

## Deep Dives

### Storage
[06_storage](./06_storage) — Give your agents persistent storage. Postgres and SQLite recommended. Also supports DynamoDB, Firestore, MongoDB, Redis, SingleStore, SurrealDB, and more.

### Knowledge & RAG
[07_knowledge](./07_knowledge) — Give your agents information to search at runtime. Covers chunking strategies (semantic, recursive, agentic), embedders, vector databases, hybrid search, and loading from URLs, S3, GCS, YouTube, PDFs, and more.

### Learning
[08_learning](./08_learning) — Unified learning system for agents. Decision logging, preference tracking, and continuous improvement.

### Evals
[09_evals](./09_evals) — Measure what matters: accuracy (LLM-as-judge), performance (latency, memory), reliability (expected tool calls), and agent-as-judge patterns.

### Reasoning
[10_reasoning](./10_reasoning) — Make agents think before they act. Three approaches:
- **Reasoning models** — Use models pre-trained for reasoning (o1, o3, etc.)
- **Reasoning tools** — Give the agent tools that enable reasoning (think, analyze)
- **Reasoning harness** — Set `reasoning=True` for chain-of-thought with tool use

### Memory
[11_memory](./11_memory) — Agents that remember. Store insights and facts about users across conversations for personalized responses.

### Models
[90_models](./90_models) — 40+ model providers. Gemini, Claude, GPT, Llama, Mistral, DeepSeek, Groq, Ollama, vLLM — if it exists, we probably support it.

### Tools
[91_tools](./91_tools) — Extend what agents can do. Web search, SQL, email, APIs, MCP, Discord, Slack, Docker, and custom tools with the `@tool` decorator.

### Integrations
[92_integrations](./92_integrations) — Connect to Discord, observability tools (Langfuse, Arize Phoenix, AgentOps, LangSmith), memory providers, and A2A protocol.

## Quality Standard

For every cookbook folder that contains runnable Python examples, include:

- `README.md` explaining intent, prerequisites, and run commands
- `TEST_LOG.md` recording run status and observations

Use `cookbook/STYLE_GUIDE.md`

Enforce in checks (fails on missing metadata):

```bash
python3 cookbook/scripts/audit_cookbook_metadata.py --scope direct --fail-on-missing
```

Check cookbook Python structure pattern:

```bash
python3 cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart
```

Run cookbooks in non-interactive batch mode with demo environment defaults:

```bash
python3 cookbook/scripts/cookbook_runner.py cookbook/00_quickstart --batch --python-bin .venvs/demo/bin/python
```

Write machine-readable run report:

```bash
python3 cookbook/scripts/cookbook_runner.py cookbook/00_quickstart --batch --json-report .context/cookbook-run.json
```

---

## Contributing

We're always adding new cookbooks. Want to contribute? See [CONTRIBUTING.md](../CONTRIBUTING.md).
