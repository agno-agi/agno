# 06_memory_and_learning

Examples for persistent memory and learning behavior.

## Files
- `learning_machine.py` - Demonstrates LearningMachine-based learning.
- `memory_manager.py` - Use MemoryManager for persistent memory across sessions.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/06_memory_and_learning/<file>.py`
