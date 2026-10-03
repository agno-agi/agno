# 02_input_output

Examples for input formats, validation schemas, streaming, and structured outputs.

## Files
- `expected_output.py` - Guide agent responses with an expected output hint.
- `input_formats.py` - Demonstrates input formats.
- `input_schema.py` - Demonstrates input schema validation.
- `output_model.py` - Return structured data using output_model with a Pydantic model.
- `output_schema.py` - Demonstrates output schema.
- `output_parse_failure.py` - Detect failed Pydantic output parsing with an error run.
- `parser_model.py` - Demonstrates parser model for structured extraction.
- `response_as_variable.py` - Capture agent response as a variable.
- `save_to_file.py` - Save agent responses to a file automatically.
- `streaming.py` - Stream agent responses token by token.
- `followup_suggestions.py` - Get a response with AI-generated follow-up suggestions.

Set `fail_on_output_parse_error=True` on Agent or Team to make failed Pydantic
output parsing end with `RunStatus.error`. The raw reply remains in `content`,
and an error event carries `error_type="output_parse_error"` and the parsing
diagnostic in its `content`. Streaming emits an error without a successful run
completion event.

The setting defaults to `False`, is ignored with `parse_response=False`, and
does not validate dictionary JSON schemas. Existing JSON recovery steps and
configured run retries still apply; model fallback is unchanged.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/02_input_output/<file>.py`
