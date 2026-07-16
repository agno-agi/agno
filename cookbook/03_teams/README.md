# Agent Teams

Cookbooks for building multi-agent teams in Agno.

## Prerequisites

- Load environment variables with `direnv allow` (for example `OPENAI_API_KEY`).
- Use `.venvs/demo/bin/python` to run examples.
- Some examples require external services (for example PostgreSQL, LanceDB, Infinity server, or AgentOS remote instances).

## Directories

- `01_quickstart/` - Core team coordination patterns, including route/broadcast/tasks and nested teams.
- `02_modes/` - Team execution modes (coordinate, route, broadcast, tasks) with examples for each.
- `03_tools/` - Custom tools and tool hook patterns.
- `04_structured_input_output/` - Structured input/output schemas, overrides, and streaming.
- `05_knowledge/` - Team knowledge, filters, and custom retrievers.
- `06_memory/` - Memory manager, agentic memory, and LearningMachine examples.
- `07_session/` - Session persistence, options, summaries, and history search.
- `08_streaming/` - Response streaming and event monitoring.
- `09_context_management/` - Context filtering, introductions, and few-shot context.
- `10_context_compression/` - Tool-result compression and compression manager usage.
- `11_reasoning/` - Multi-purpose reasoning team patterns.
- `12_learning/` - Team learning patterns (always, configured, entity memory, session planning, learned knowledge, decision log).
- `13_hooks/` - Input pre-hooks, output post-hooks, and stream hooks.
- `14_run_control/` - Cancellation, retries, model inheritance, remote teams, and background execution.
- `15_distributed_rag/` - Multi-member distributed retrieval with PgVector/LanceDB/reranking.
- `16_search_coordination/` - Coordinated RAG/search patterns across members.
- `17_dependencies/` - Runtime dependencies in context, tools, and member flows.
- `18_guardrails/` - Prompt-injection, moderation, and PII protections.
- `19_multimodal/` - Audio, image, and video workflows.
- `20_human_in_the_loop/` - Confirmation, external execution, and user-input-required flows.
- `21_state/` - Shared session state across members and nested teams.
- `22_metrics/` - Team/session/member metrics inspection.
