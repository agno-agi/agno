# Tuning Engines Cookbook

Tuning Engines exposes an OpenAI-compatible endpoint for teams that want Agno
agents to run through a governed AI control plane. Agno owns the agent behavior,
tools, memory, and orchestration. Tuning Engines centralizes model access,
policy checks, audit logs, traces, and usage/cost reporting.

## 1. Create an inference key

Create a Tuning Engines inference key and enable the model alias you want the
agent to use.

## 2. Export environment variables

```shell
export TUNING_ENGINES_API_KEY=sk-te-your-inference-key
export TUNING_ENGINES_MODEL=gpt-4o
```

If you run Tuning Engines behind a custom host, also set:

```shell
export TUNING_ENGINES_BASE_URL=https://your-host.example.com/v1
```

## 3. Install libraries

```shell
uv pip install -U agno openai
```

## 4. Run the example

```shell
python cookbook/90_models/tuning_engines/basic.py
```

The example uses the dedicated `TuningEngines` model provider:

```python
from agno.agent import Agent
from agno.models.tuning_engines import TuningEngines

agent = Agent(model=TuningEngines(id="gpt-4o"))
```
