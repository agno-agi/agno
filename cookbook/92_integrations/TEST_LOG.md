# TEST_LOG.md - 92 Integrations

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

## A2A (Agent-to-Agent)

### a2a/basic_agent/__main__.py — SKIP (server component)
### a2a/basic_agent/basic_agent.py — SKIP (server component)
### a2a/basic_agent/client.py — SKIP (needs A2A server running)

---

## Discord

### discord/basic.py — SKIP (needs DISCORD_BOT_TOKEN)
### discord/agent_with_media.py — SKIP (needs DISCORD_BOT_TOKEN)
### discord/agent_with_user_memory.py — SKIP (needs DISCORD_BOT_TOKEN)

---

## Memory

### memory/mem0_integration.py — SKIP (missing package: mem0ai)
### memory/memori_integration.py — SKIP (missing package: memori)
### memory/zep_integration.py — SKIP (missing package: zep-cloud)

---

## Observability

### observability/agent_ops.py — SKIP (missing package: agentops)
### observability/arize_phoenix_moving_traces_to_different_projects.py — SKIP (missing package: phoenix)
### observability/arize_phoenix_via_openinference_local.py — SKIP (missing package: phoenix)
### observability/arize_phoenix_via_openinference.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/atla_op.py — SKIP (missing package: atla)
### observability/langfuse_via_openinference.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/langfuse_via_openinference_response_model.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/langfuse_via_openlit.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/langsmith_via_openinference.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/langtrace_op.py — SKIP (missing package: langtrace)
### observability/langwatch_op.py — SKIP (missing package: langwatch)
### observability/logfire_via_openinference.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/maxim_ops.py — SKIP (missing package: maxim)
### observability/opik_via_openinference.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/trace_to_database.py — FAIL (v2.5 regression: Agent._run method no longer exists, openinference monkey-patch fails)
### observability/traceloop_op.py — SKIP (missing package: traceloop)
### observability/weave_op.py — SKIP (missing package: weave)

### observability/teams/langfuse_via_openinference_team.py — SKIP (missing package: opentelemetry OTLP exporter)

### observability/workflows/arize_phoenix_via_openinference_workflow.py — SKIP (missing package: opentelemetry OTLP exporter)
### observability/workflows/langfuse_via_openinference_workflows.py — SKIP (missing package: opentelemetry OTLP exporter)

---

## RAG

### rag/agentic_rag_infinity_reranker.py — SKIP (missing package: infinity_client)
### rag/agentic_rag_with_lightrag.py — SKIP (missing package: wikipedia)
### rag/local_rag_langchain_qdrant.py — SKIP (missing package: ollama)

---

## SurrealDB

### surrealdb/custom_memory_instructions.py — SKIP (missing package: surrealdb)
### surrealdb/db_tools_control.py — SKIP (missing package: surrealdb)
### surrealdb/memory_creation.py — SKIP (missing package: surrealdb)
### surrealdb/memory_search_surreal.py — SKIP (missing package: surrealdb)
### surrealdb/standalone_memory_surreal.py — SKIP (missing package: surrealdb)

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 0    | 1    | 36   | 37    |

### Framework Bug

- **trace_to_database.py**: OpenInference instrumentation tries to monkey-patch `Agent._run` which no longer exists in v2.5 (moved to `agno/agent/_run.py` module functions). This breaks all openinference-based tracing integrations.

### Notes

- Nearly all integrations require optional packages not in demo venv
- The openinference/v2.5 incompatibility affects multiple observability integrations (langfuse, arize, langsmith, logfire, opik)
