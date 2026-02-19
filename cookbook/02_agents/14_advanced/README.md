# 14_advanced

Advanced examples covering caching, compression, concurrency, events, retries, debugging, culture, and serialization.

## Files
- `01_create_cultural_knowledge.py` - Create cultural knowledge for agents.
- `02_use_cultural_knowledge_in_agent.py` - Use cultural knowledge in an agent.
- `03_automatic_cultural_management.py` - Automatic cultural context management.
- `04_manually_add_culture.py` - Manually add culture to an agent.
- `advanced_compression.py` - Advanced context compression strategies.
- `agent_serialization.py` - Serialize and deserialize agents.
- `background_execution.py` - Run agents in the background.
- `background_execution_structured.py` - Background execution with structured output.
- `basic_agent_events.py` - Listen to agent lifecycle events.
- `cache_model_response.py` - Cache model responses.
- `cancel_run.py` - Cancel a running agent.
- `compression_events.py` - Events during context compression.
- `concurrent_execution.py` - Run multiple agents concurrently.
- `custom_cancellation_manager.py` - Custom cancellation logic.
- `custom_logging.py` - Custom logging configuration.
- `debug.py` - Enable debug mode for verbose output.
- `metrics.py` - Access agent run metrics.
- `reasoning_agent_events.py` - Events during reasoning steps.
- `retries.py` - Retry configuration with exponential backoff.
- `tool_call_compression.py` - Compress tool call results in context.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/14_advanced/<file>.py`
