# Agno Cookbooks

Hundreds of examples. Copy, paste, run.

## Where to Start

**New to Agno?** Start with [00_quickstart](./00_quickstart) — it walks you through the fundamentals, with each cookbook building on the last.

**Want to see something real?** Jump to [01_demo](./01_demo) — advanced use cases. Run the examples, break them, learn from them.

**Want to build something complete?** Browse [examples](./examples) — small products you can run and point your AI apps at. Two files per folder: one builds the agent and serves it, `test.py` drives it from the command line.

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
[06_storage](./06_storage) — Give your agents persistent storage. Postgres and SQLite recommended. Also supports DynamoDB, Firestore, MongoDB, Redis, SingleStore, SurrealDB, Valkey, and more.

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

### Context
[12_context](./12_context) — Plug an external source into an agent as a natural-language tool. Local directories, project workspaces, the web via Exa, databases, Slack, Google Drive, and MCP servers, all behind one `ContextProvider` API.

### FileSystem
[13_filesystem](./13_filesystem) — Give your agent a durable, private filesystem for its own working state: records of what it has processed, decisions, progress checkpoints. Database-backed by default, local disk optional.

### Models
[90_models](./90_models) — 40+ model providers. Gemini, Claude, GPT, Llama, Mistral, DeepSeek, Groq, Ollama, vLLM — if it exists, we probably support it.

### Tools
[91_tools](./91_tools) — Extend what agents can do. Web search, SQL, email, APIs, MCP, Discord, Slack, Docker, and custom tools with the `@tool` decorator.

### Components as Config
[93_components](./93_components) — Save agents, teams and workflows to a database and load them back, so a running system can be versioned, shared and restored.

### Environments
[environments](./environments) — Verification and dataset generation. Run an agent K times against hard tasks, score every attempt, read the pass-rate grid, and export the passing trajectories as a fine-tuning dataset.

### Data Labeling
[data_labeling](./data_labeling) — Agents for labeling, classification, and synthetic data generation, from single-label prompts to juries and DPO pair generation.

### Other Frameworks
[frameworks](./frameworks) — Run LangGraph, DSPy, the Claude Agent SDK and Antigravity agents inside Agno, and serve them from the same AgentOS as your native agents.

### Integrations
[integrations](./integrations) — Partner integrations. [Parallel](https://parallel.ai) for web-scale search, extraction, and deep research; SurrealDB for agent memory.

### Gemini 3
[gemini_3](./gemini_3) — The same progressive build as the quickstart, on Google Gemini end to end.

### Observability
[observability](./observability) — Trace and monitor agents, teams, and workflows: Langfuse, Arize Phoenix, AgentOps, LangSmith, MLflow, Weave, Logfire, and more (via OpenInference, OpenLIT, and autolog).

## Quality Standard

Every folder of runnable examples carries a `TEST_LOG.md` recording what was run and what
came back, and every example file opens with a docstring saying what it is and how to run it.
Add a `README.md` where a folder needs more than its files can say: prerequisites, a service
to start, an ordering to follow. Conventions live in [STYLE_GUIDE.md](./STYLE_GUIDE.md).

Check cookbook Python structure pattern:

```bash
python3 cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart
```

Run a folder of cookbooks non-interactively (uses `.venvs/demo/bin/python` unless you pass `--python-bin`):

```bash
python3 cookbook/scripts/cookbook_runner.py cookbook/00_quickstart
```

Write machine-readable run report:

```bash
python3 cookbook/scripts/cookbook_runner.py cookbook/00_quickstart --json-report .context/cookbook-run.json
```

---

## Contributing

We're always adding new cookbooks. Want to contribute? See [CONTRIBUTING.md](../CONTRIBUTING.md).
