# Message Routing Agent

Turn customer messages into validated routing decisions.
A small runnable companion to [Message Routing Agent](https://docs.agno.com/use-cases/structured-output-as-api).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/routing_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python routing_api.py
```

In a second terminal, activate the environment and run `python demo.py`. The
caller validates the structured result and selects `billing-support` for the
sample duplicate-charge request. Ambiguous results and API or validation failures
select `manual-review`; urgent requests select `priority-support`.

`routing_schema.py` is shared by the agent and caller. Each classification is
independent and performs no account actions. The service binds to localhost and
accepts form fields at `/agents/message-router/runs`. Test accuracy on your own
messages before connecting a queue. The demo only prints the chosen queue.

## Build further

Read the linked use-case guide for the next step. Choose a
[deployment template](https://docs.agno.com/deploy/introduction) when you need a
fully deployable application. All examples here use OpenAI's `gpt-5.6`; model
responses vary. See [TEST_LOG.md](TEST_LOG.md) for what has been validated.

## Validate locally

```bash
uv pip install pytest
python -m pytest test_contracts.py -q
```

These deterministic checks do not call a model or evaluate answer quality.
