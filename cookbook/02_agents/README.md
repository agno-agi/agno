# Agno Agents Cookbook

Practical examples for building agents with Agno, organized by feature area.

## Directories

| # | Directory | Description | Files |
|:--|:----------|:------------|:------|
| 01 | [01_quickstart](./01_quickstart/) | Starter examples: basic agent, instructions, tools | 3 |
| 02 | [02_input_output](./02_input_output/) | Input formats, output schemas, streaming, structured output | 9 |
| 03 | [03_context_management](./03_context_management/) | Instructions, system messages, few-shot learning | 6 |
| 04 | [04_tools](./04_tools/) | Callable factories, tool choice, tool call limits | 5 |
| 05 | [05_state_and_session](./05_state_and_session/) | Session state, chat history, persistence | 12 |
| 06 | [06_memory_and_learning](./06_memory_and_learning/) | Memory manager, learning machine | 2 |
| 07 | [07_knowledge](./07_knowledge/) | RAG, custom retrievers, knowledge filters | 8 |
| 08 | [08_guardrails](./08_guardrails/) | PII detection, prompt injection, custom guardrails | 5 |
| 09 | [09_hooks](./09_hooks/) | Pre/post hooks, tool hooks, stream hooks | 5 |
| 10 | [10_human_in_the_loop](./10_human_in_the_loop/) | Confirmation flows, user input, external execution | 7 |
| 11 | [11_approvals](./11_approvals/) | Approval workflows, audit trails | 11 |
| 12 | [12_multimodal](./12_multimodal/) | Image, audio, video processing | 10 |
| 13 | [13_reasoning](./13_reasoning/) | Multi-step reasoning, reasoning models | 2 |
| 14 | [14_advanced](./14_advanced/) | Caching, compression, events, retries, concurrency, culture | 20 |
| 15 | [15_dependencies](./15_dependencies/) | Dependency injection in tools and context | 3 |
| 16 | [16_skills](./16_skills/) | Agent skills with scripts and reference docs | 1 |

**Total: 111 files across 16 directories**

## Prerequisites

- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require PostgreSQL with pgvector: `./cookbook/scripts/run_pgvector.sh`

## Run

```bash
.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py
```
