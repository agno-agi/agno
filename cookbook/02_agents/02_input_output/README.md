# 02_input_output

Examples for input formats, validation schemas, streaming, and structured outputs.

## Files
- `expected_output.py` - Guide agent responses with an expected output hint.
- `input_formats.py` - Demonstrates input formats.
- `input_schema.py` - Demonstrates input schema validation.
- `output_model.py` - Return structured data using output_model with a Pydantic model.
- `output_schema.py` - Demonstrates output schema.
- `parser_model.py` - Demonstrates parser model for structured extraction.
- `response_as_variable.py` - Capture agent response as a variable.
- `save_to_file.py` - Save agent responses to a file automatically.
- `streaming.py` - Stream agent responses token by token.
- `followup_suggestions.py` - Get a response with AI-generated follow-up suggestions.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/02_input_output/<file>.py`
