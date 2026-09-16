# Personal Agent

Pip keeps projects, tasks, and decisions in durable notes. Start here for an agent you can understand in one file.

## Run locally

From the repository root:

```bash
cd cookbook/examples/personal_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

A downloaded example uses the same commands after changing into its directory.
`requirements.txt` lists the runtime dependencies; no uv project is needed. Export
credentials in your shell. On Windows, activate with `.venv\Scripts\Activate.ps1`.
Model calls use `openai:gpt-5.6`.

## Try the tutorial story

`demo.py` sends the exact tutorial brief: Jen reviews an onboarding guide; sending
the draft by Thursday and testing with a new user by Friday are the next steps.
It records that the draft was sent and that a checklist was chosen because it is
easier to keep up to date. It then asks in a fresh session what is outstanding.
Expect the user test to remain outstanding and the draft task to remain complete.
The demo prints the actual saved files, so recall can be checked against notes.

```bash
python demo.py --recall-only
python personal_agent.py
```

The second command starts the tutorial's AgentOS at `http://localhost:7777`;
browse `/docs` or connect the Control Plane locally. The downloadable
[`personal_agent.py`](personal_agent.py) has **no helper imports** and uses only
`agno[os,sqlite]`, `openai`, and `OPENAI_API_KEY`, as in the tutorial.
Its code and prompt match the live tutorial input exactly; see
[TUTORIAL_PARITY.md](TUTORIAL_PARITY.md) for hashes.

## Storage and identity

`personal_agent.db` holds notes, sessions, and traces in the working directory.
`personal-agent/{user_id}` separates notes by the user ID supplied to the run;
`demo.py` uses `tutorial-user`. Notes survive process restarts and fresh session
IDs. Sessions store chat history separately. Pip chooses document names by project
or topic; there is no prescribed task/note filename.

This starter has no authentication configuration. Caller-supplied local identities
are not authenticated identities; keep the server on your trusted local machine.
Namespaces are normalized, so IDs differing only in case can collide. Use stable,
lowercase IDs. Notes stay in your database; model requests send relevant notes and
conversation content to OpenAI. Traces can contain this content too.

## Extend it

Continue the [personal-agent tutorial](https://docs.agno.com/first-agent) through
Slack and Railway when you need an everyday interface and a hosted service. For learning
about people and preferences automatically across conversations, move to
[Second Brain](../second_brain). This starter deliberately keeps learning stores out.

## Validate

From this example directory:

```bash
uv pip install pytest pytest-asyncio
python -m pytest test_contracts.py -q
```

See [TEST_LOG.md](TEST_LOG.md) for measured results and limitations. To check the
checkout instead of the published package, prefix the command with
`PYTHONPATH=../../../libs/agno` while running from this directory. The source
revision is recorded in the collection's [validation report](../VALIDATION.md).
