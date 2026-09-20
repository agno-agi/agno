# TypeSafe (Jev) Cookbook

> Note: Fork and clone this repository if needed

[Jev](https://docs.typesafe.ai) is TypeSafe's System One model. It is not a chat model: it does not generate text. It reads an input and answers typed questions about it - pick one option, rate along levels, or judge a yes/no - and returns calibrated probabilities in roughly a tenth of a second. The default model id is `jev-latest`.

In Agno, Jev is a decision model for teams and workflows:

| Use | How |
|-----|-----|
| Fill an `output_schema` | `Agent(model=Jev(), output_schema=MySchema)` - `bool`, `Literal`, `Enum`, `IntEnum` and `List[Literal]` fields, each asked using the field description |
| Raw System One questions | `Jev(questions={...})` - the run content is the answers as JSON |
| Lead a route team | `Team(mode=TeamMode.route, model=Jev(), ...)` - see `cookbook/03_teams/02_modes/route/04_jev_router.py` |
| Judge a broadcast panel | `Team(mode=TeamMode.broadcast, model=Jev(), output_schema=...)` - see `cookbook/03_teams/02_modes/broadcast/05_jev_panel_judge.py` |
| Classify before a workflow Router | see `cookbook/04_workflows/05_conditional_branching/router_jev_classifier.py` |
| Call tools with closed-set arguments | `Agent(model=Jev(), tools=[...])` - arguments must be `Literal`, `bool` or `List[Literal]` |

Every probability and confidence behind a run is on `run.model_provider_data`.

Jev cannot write replies, summaries, memories or followups, and it cannot lead `coordinate` or `tasks` teams. Team members need their own generative model - a member without one inherits Jev from the team. Related: `JevGuardrail` (`cookbook/02_agents/08_guardrails/jev_guardrail.py`) and `JevTools` (`cookbook/91_tools/jev_tools.py`).

### 1. Create and activate a virtual environment

Follow the [Development setup](../../../CONTRIBUTING.md#development-setup) instructions. The TypeSafe SDK needs Python 3.10 or newer.

### 2. Export your API keys

Create a TypeSafe key at https://console.typesafe.ai/keys.

```shell
export TYPESAFE_API_KEY=***
export OPENAI_API_KEY=***   # only for tool_use.py, which falls back to a generative model
```

### 3. Install libraries

```shell
uv pip install -U typesafe-sdk openai agno
```

### 4. Run the examples

```shell
python cookbook/90_models/typesafe/basic.py
python cookbook/90_models/typesafe/async_basic.py
python cookbook/90_models/typesafe/raw_questions.py
python cookbook/90_models/typesafe/tool_use.py
```

### Writing questions for Jev

- Ask one narrow judgment per field. Split a broad question into several and combine the answers in code.
- Jev reads literally. Put the exact condition in the field description; field names are never sent to the model.
- Describe the options: `Field(..., json_schema_extra={"criteria": {"billing": "Charges and refunds", ...}})`. For an `IntEnum` or a scored `int`, `criteria` is the ordered list of level descriptions.
- An `Optional[Literal[...]]` field gains a "none" option, so Jev can say nothing fits.
- A `bool` is true when the probability reaches `Jev(threshold=0.5)`; override one field with `json_schema_extra={"threshold": 0.8}`.
- Keep counting, arithmetic and date comparison in code.

### Available models

| Model id | Notes |
|----------|-------|
| `jev-latest` | The most recent stable release (default) |
| `jev-preview` | The most recent release, stable or not |
| `jev-1.13.0` | A pinned version; use one when you have tuned thresholds against it |
