# input_and_output

Examples for input formats, validation schemas, and structured outputs.

## Files
- `input_formats.py` - Demonstrates input formats.
- `input_schema.py` - Demonstrates input schema.
- `output_schema.py` - Demonstrates output schema.
- `parser_model.py` - Demonstrates parser model.
- `response_as_variable.py` - Demonstrates response as variable.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
