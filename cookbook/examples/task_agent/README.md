# Task Agent

Let a customer list and complete tasks through bounded product tools.
A small runnable companion to [Task Agent](https://docs.agno.com/use-cases/product-agents/overview).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/task_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

The demo acts as Alice: it completes task-1, lists it again, then requests Bob's
task-2. The last request must return "Task not found" and leave Bob's record
unchanged. The model chooses a task ID; the tool checks `RunContext.user_id`.

Run `python task_agent.py` to serve the agent on localhost. For example:

```bash
curl http://localhost:7777/agents/task-agent/runs \
  -F 'message=List my tasks, then mark task-1 complete.' \
  -F 'user_id=alice' -F 'session_id=alice-project' -F 'stream=false'
```

Tasks are fictional in-memory records and reset when the process restarts.
Conversation history uses `task-agent.db`. Caller-supplied user IDs are local demo
identities; configure verified authentication and user isolation before exposing
this service. Replace the dictionary with your application's authorized services.
The directory and agent ID distinguish this action example from
[Product Agent](../product_agent), which serves indexed product knowledge.

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
