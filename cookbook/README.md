# Agno Cookbooks

Hundreds of examples. Copy, paste, run. Build agents that actually work.

## Where to Start

**New to Agno?** Start with [00_getting_started](./00_getting_started) — it walks you through the fundamentals, with each cookbook building on the last.

**Want to see something real?** Jump to [01_demo](./01_demo) — a complete multi-agent system using AgentOS. Run it, break it, learn from it.

**Know what you're building?** Find your use case below.

---

## Build by Use Case

### I want to build a single agent
→ [03_agents](./03_agents) — The atomic unit of Agno. Start here for tools, RAG, structured outputs, multimodal, guardrails, and more.

### I want agents working together
→ [04_teams](./04_teams) — Coordinate multiple agents. Async flows, shared memory, distributed RAG, reasoning patterns.

### I want to orchestrate complex processes
→ [05_workflows](./05_workflows) — Chain agents, teams, and functions into automated pipelines.

### I want to deploy and manage agents
→ [06_agent_os](./06_agent_os) — Deploy to web APIs, Slack, WhatsApp, and more. The control plane for your agent systems.

---

## Deep Dives

### Knowledge & RAG
[08_knowledge](./08_knowledge) — Give your agents information to search at runtime. Covers chunking strategies (semantic, recursive, agentic), embedders, vector databases, hybrid search, and loading from URLs, S3, GCS, YouTube, PDFs, and more.

### Memory
[09_memory](./09_memory) — Agents that remember. Store insights and facts about users across conversations for personalized responses.

### Reasoning
[10_reasoning](./10_reasoning) — Make agents think before they act. Three approaches:
- **Reasoning models** — Use models pre-trained for reasoning (o1, o3, etc.)
- **Reasoning tools** — Give any agent tools that enable reasoning
- **Reasoning agents** — Set `reasoning=True` for chain-of-thought with tool use

### Databases
[07_database](./07_database) — Postgres and SQLite recommended. Also supports DynamoDB, Firestore, MongoDB, Redis, SingleStore, SurrealDB, and more.

### Models
[11_models](./11_models) — 40+ model providers. Gemini, Claude, GPT, Llama, Mistral, DeepSeek, Groq, Ollama, vLLM — if it exists, we probably support it.

### Tools
[14_tools](./14_tools) — Extend what agents can do. Web search, SQL, email, APIs, MCP, Discord, Slack, Docker, and custom tools with the `@tool` decorator.

---

## Production Ready

### Evals
[12_evals](./12_evals) — Measure what matters: accuracy (LLM-as-judge), performance (latency, memory), reliability (expected tool calls), and agent-as-judge patterns.

### Integrations
[13_integrations](./13_integrations) — Connect to Discord, observability tools (Langfuse, Arize Phoenix, AgentOps, LangSmith), memory providers, and A2A protocol.

## Real World Examples

[02_examples](./02_examples) — Complete, production-style examples. Stop reading docs, start building.

---

## Contributing

We're always adding new cookbooks. Want to contribute? See [CONTRIBUTING.md](./CONTRIBUTING.md).
