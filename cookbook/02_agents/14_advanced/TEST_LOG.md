# Test Log — 14_advanced

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| 01_create_cultural_knowledge.py | PASS | Creates cultural knowledge entries in PgVector |
| 02_use_cultural_knowledge_in_agent.py | PASS | Agent uses cultural knowledge to guide Dockerfile response |
| 03_automatic_cultural_management.py | PASS | Automatic cultural management, ramen tips with cultural context |
| 04_manually_add_culture.py | PASS | Manual culture addition, Docker response with cultural context |
| advanced_compression.py | PASS | Token limit compression triggered at 5000 tokens (API warnings for token counting are non-fatal) |
| agent_serialization.py | PASS | Agent serialized to JSON and loaded, responds correctly |
| background_execution.py | PASS | Background run created, cancelled, status transitions verified |
| background_execution_structured.py | PASS | Structured background execution, 3 questions answered with COMPLETED status |
| basic_agent_events.py | PASS | Events: ToolCallStarted, ToolCallCompleted, RunCompleted for stock price |
| cache_model_response.py | PASS | Cached response returned in 0.001s on second call |
| cancel_run.py | PASS | Run cancelled successfully |
| compression_events.py | PASS | Compression events: CompressionStarted/Completed with ratio logged |
| concurrent_execution.py | PASS | Concurrent agent execution, Cohere and Google reports generated |
| custom_cancellation_manager.py | PASS | Custom cancellation manager, run cancelled with state cleanup |
| custom_logging.py | PASS | Custom logging with sleep tips |
| debug.py | PASS | Debug mode with joke response |
| metrics.py | PASS | Metrics output with tokens, duration, cost |
| reasoning_agent_events.py | PASS | Reasoning events for Treaty of Versailles analysis |
| retries.py | PASS | Retry mechanism with web search, AI agents response |
| tool_call_compression.py | PASS | Tool call compression after limit hit, DuckDuckGo search |
