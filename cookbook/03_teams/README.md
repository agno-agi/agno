# Agent Teams

Cookbooks for building multi-agent teams in Agno.

## Prerequisites

- Load environment variables with `direnv allow` (for example `OPENAI_API_KEY`).
- Use `.venvs/demo/bin/python` to run examples.
- Some examples require external services (for example PostgreSQL, LanceDB, Infinity server, or AgentOS remote instances).

## Directories

- `01_quickstart/` - Core team coordination patterns, including route/broadcast/tasks and nested teams.
- `context_compression/` - Tool-result compression and compression manager usage.
- `context_management/` - Context filtering, introductions, and few-shot context.
- `dependencies/` - Runtime dependencies in context, tools, and member flows.
- `distributed_rag/` - Multi-member distributed retrieval with PgVector/LanceDB/reranking.
- `guardrails/` - Prompt-injection, moderation, and PII protections.
- `hooks/` - Input pre-hooks, output post-hooks, and stream hooks.
- `human_in_the_loop/` - Confirmation, external execution, and user-input-required flows.
- `knowledge/` - Team knowledge, filters, and custom retrievers.
- `learning/` - Team learning patterns (always, configured, entity memory, session planning, learned knowledge, decision log).
- `memory/` - Memory manager, agentic memory, and LearningMachine examples.
- `metrics/` - Team/session/member metrics inspection.
- `modes/` - Team execution modes (coordinate, route, broadcast, tasks) with examples for each.
- `multimodal/` - Audio, image, and video workflows.
- `other/` - Additional patterns (background execution).
- `reasoning/` - Multi-purpose reasoning team patterns.
- `run_control/` - Cancellation, retries, model inheritance, and remote teams.
- `search_coordination/` - Coordinated RAG/search patterns across members.
- `session/` - Session persistence, options, summaries, and history search.
- `state/` - Shared session state across members and nested teams.
- `streaming/` - Response streaming and event monitoring.
- `structured_input_output/` - Structured input/output schemas, overrides, and streaming.
- `task_mode/` - Task mode examples (basic, parallel, tools, async, dependencies, custom tools, multi-run).
- `tools/` - Custom tools and tool hook patterns.
