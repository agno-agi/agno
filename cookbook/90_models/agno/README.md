# Agno Gateway

Use any model through the Agno gateway with a single Agno API key. The `Agno` model
class talks to the gateway over plain HTTP (httpx) using the OpenAI chat-completions
schema, so it needs **no provider SDK installed** (`openai`, `anthropic`, etc.). The
gateway routes to every provider by the model id prefix and handles provider
specifics; billing runs through your Agno account.

### 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Authenticate

```shell
export AGNO_API_KEY=***
```

You can also bring your own provider key (BYOK): if `AGNO_API_KEY` is unset, the
class falls back to the provider key for the id prefix (e.g. `OPENAI_API_KEY` for
`openai/...`). Either way, traffic flows through the gateway.

### 3. Install libraries

```shell
uv pip install -U agno
```

No provider SDK is required.

### 4. Run the basic example

```shell
python cookbook/90_models/agno/basic.py
```

### Addressing models

Models are addressed as `<provider>/<model>`. Switch providers by changing the prefix:

```python
from agno.models.agno import Agno

Agno(id="openai/gpt-5.4")
Agno(id="google/gemini-3-flash")
```

> Anthropic support is planned via the messages endpoint. For now, `anthropic/*` model
> ids raise a clear error rather than returning empty content.

### String model syntax

```python
Agent(model="agno:openai/gpt-5.4")
```

### Examples

| File | What it shows |
| --- | --- |
| `basic.py` | Sync, streaming, and async runs (managed `AGNO_API_KEY`) |
| `bring_your_own_key.py` | BYOK: provider key by prefix, or explicit `api_key=` |
| `tool_use.py` | Function calling: single, parallel, streaming, and async |
| `structured_output.py` | Typed responses with `output_schema` (native + JSON mode) |
| `metrics.py` | Per-message and aggregated token metrics |
| `image_input.py` | Image input to a vision model |
| `pdf_input.py` | PDF / file input |
| `reasoning_effort.py` | `reasoning_effort` on a reasoning model |
| `db.py` | Persistence and conversation history (`PostgresDb`) |
| `memory.py` | User memories and session summaries |
| `knowledge.py` | Retrieval-augmented generation with `PgVector` |
| `audio_input.py` | Audio input to an audio model |
| `audio_output.py` | Audio (speech) output from an audio model |

Agent-level features (`db.py`, `memory.py`, `knowledge.py`) are model-agnostic and work
unchanged through the gateway; they need a local Postgres container
(`./cookbook/scripts/run_pgvector.sh`).

### Configuration

| Variable | Purpose |
| --- | --- |
| `AGNO_API_KEY` | Your Agno API key (managed billing) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ... | Bring your own provider key (used for the matching id prefix) |
| `AGNO_GATEWAY_BASE_URL` | Override the gateway base URL (optional) |
