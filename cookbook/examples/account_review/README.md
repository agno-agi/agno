# Account Review

Collect an account snapshot, draft a review, and ask before saving it.
A small runnable companion to [Account Review](https://docs.agno.com/use-cases/workflow-automation).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/account_review
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

The workflow uses a synthetic Acme snapshot: weekly active users fell from 30
to 18, with three open support tickets. Read the draft at the prompt. Enter `y`
to write `approved-review.md`; any other answer skips the save. A later approved
run replaces the file. Rejection leaves an existing approved file unchanged.

`account_review.py` contains the complete workflow. SQLite stores local run state
in `account-review.db`. The model should separate the observed 40% decline from
possible explanations and propose a follow-up question. The approval only controls
the local save step; it sends no messages or external actions.

The guide continues with Postgres, AgentOS background execution, and a reviewer
that can resume a stored run. Use that continuation when building a deployed
review service.

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
