# culture

Examples for creating and applying shared cultural knowledge.

## Files
- `01_create_cultural_knowledge.py` - Demonstrates 01 create cultural knowledge.
- `02_use_cultural_knowledge_in_agent.py` - Demonstrates 02 use cultural knowledge in agent.
- `03_automatic_cultural_management.py` - Demonstrates 03 automatic cultural management.
- `04_manually_add_culture.py` - Demonstrates 04 manually add culture.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
