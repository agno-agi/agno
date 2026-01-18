# Agno Cookbooks

Hundreds of examples. Copy, paste, run. Build agents that actually work.

## Where to Start

**New to Agno?** Start with [00_quickstart](./00_quickstart) — it walks you through the fundamentals, with each cookbook building on the last.

**Want to see something real?** Jump to [01_showcase](./01_showcase) — advanced use cases. Run the examples, break them, learn from them.

**Know what you're building?** Find your use case below.

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

### Knowledge & RAG
[07_knowledge](./07_knowledge) — Give your agents information to search at runtime. Covers chunking strategies (semantic, recursive, agentic), embedders, vector databases, hybrid search, and loading from URLs, S3, GCS, YouTube, PDFs, and more.

### Memory
[80_memory](./80_memory) — Agents that remember. Store insights and facts about users across conversations for personalized responses.

### Reasoning
[81_reasoning](./81_reasoning) — Make agents think before they act. Three approaches:
- **Reasoning models** — Use models pre-trained for reasoning (o1, o3, etc.)
- **Reasoning tools** — Give any agent tools that enable reasoning
- **Reasoning agents** — Set `reasoning=True` for chain-of-thought with tool use

### Learning
[08_learning](./08_learning) — Unified learning system for agents. Decision logging, preference tracking, and continuous improvement.

### Storage
[06_storage](./06_storage) — Postgres and SQLite recommended. Also supports DynamoDB, Firestore, MongoDB, Redis, SingleStore, SurrealDB, and more.

### Models
[92_models](./92_models) — 40+ model providers. Gemini, Claude, GPT, Llama, Mistral, DeepSeek, Groq, Ollama, vLLM — if it exists, we probably support it.

### Tools
[90_tools](./90_tools) — Extend what agents can do. Web search, SQL, email, APIs, MCP, Discord, Slack, Docker, and custom tools with the `@tool` decorator.

---

## Production Ready

### Evals
[09_evals](./09_evals) — Measure what matters: accuracy (LLM-as-judge), performance (latency, memory), reliability (expected tool calls), and agent-as-judge patterns.

### Integrations
[91_integrations](./91_integrations) — Connect to Discord, observability tools (Langfuse, Arize Phoenix, AgentOps, LangSmith), memory providers, and A2A protocol.

---

## Contributing

We're always adding new cookbooks. Want to contribute? See [CONTRIBUTING.md](./CONTRIBUTING.md).
