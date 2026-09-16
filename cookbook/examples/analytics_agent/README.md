# Analytics Agent

Answer business questions using SQL and explicit metric definitions.
A small runnable companion to [Analytics Agent](https://docs.agno.com/use-cases/data-agents/overview).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/analytics_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python seed_data.py
python demo.py
```

The seed script creates three synthetic subscriptions in `analytics.db`. Expect
active MRR of **$2,000**, from Acme ($1,200) and Beacon ($800), with Cedar excluded
because it is cancelled. The answer should include the SQL and metric definition.
The second question asks why Cedar cancelled; the table cannot establish a reason.

The SQLite URI opens this database read-only; attempts to update its rows fail.
This protects the seeded database, not every resource the process can access.
Use restricted database credentials and tenant policies for real business data.
Re-running the seed script preserves existing rows. See
[Dash](https://docs.agno.com/deploy/templates/dash/overview) for a larger analytics
application with richer business context.

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
