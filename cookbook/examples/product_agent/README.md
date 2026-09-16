# Product Agent

Answer product questions from your documentation through an HTTP API. Your app
can call the service, keep a conversation open for follow-ups, and stream answers.
This is the complete, consistently named example for
[Agents as API](https://docs.agno.com/use-cases/agents-as-api).

## Run locally

From the repository root:

```bash
cd cookbook/examples/product_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python load_knowledge.py
python product_agent.py
```

For a downloaded directory, start there. On Windows, activate with
`.venv\Scripts\Activate.ps1`. The loader indexes `product.md`, a fictional Acme
Reports guide; replace it with your product documentation. Loading generates
OpenAI embeddings with `text-embedding-3-small`. Answers use `openai:gpt-5.6`.
Only an OpenAI API key is needed; no separate database service is required.

In another terminal, activate this example's environment and run the API demo:

```bash
source .venv/bin/activate
python demo.py
```

It asks how to schedule a weekly report, then asks which plan and permissions are
needed in the same session. Expect the answer to name the Team plan and workspace
admins, citing Product documentation. It then streams an answer about exporting
filtered rows. Open `http://localhost:7777/docs` to inspect the API.

## Call it from your application

```bash
curl http://localhost:7777/agents/product-agent/runs \
  -F 'message=How do I schedule a weekly report in Acme Reports?' \
  -F 'user_id=demo-user' \
  -F 'session_id=product-questions' \
  -F 'stream=false'
```

Reuse the user and session IDs for "Which plan do I need for that, and who can
configure it?" The response includes `content`, `run_id`, and `session_id`.
Use a new session ID for a separate conversation. Set `stream=true` and use
`curl -N` for Server-Sent Events; `demo.py` shows both request modes.

The agent searches the indexed documentation and names its source. Try asking
about an undocumented feature: it should explain the gap. It treats retrieved
text as reference material, not instructions. Verify answers against your docs.

## Storage and updates

ChromaDB hybrid search combines semantic and keyword retrieval. Its persistent
index is in `data/chromadb`; SQLite in `data/agents.db` stores sessions, the content
catalog, and traces. Restarting the service preserves the index and conversations.
The last three runs provide context for follow-ups. Run `python load_knowledge.py`
after editing `product.md` to update the index; restarting alone does not reindex.

Every caller can search this shared product documentation. Caller-supplied user
IDs are local demo labels, not authentication. The server binds to loopback.
Relevant documents and conversation content are sent to OpenAI; tracing can store
that content too. This is a local API example, not a production template or a
multi-tenant authorization implementation.

## Build further

Use this small example to understand the API, then choose a
[deployment template](https://docs.agno.com/deploy/introduction) when you need a
full deployable service. The later setup should use Postgres/PgVector, durable
storage, verified authentication and user isolation, and suitable browser origins.
Persistent sessions alone do not enable durable background execution.

Add bounded product actions or structured responses as your application needs
them. [Support Agent](../support_agent) shows a different job: preparing a local
handoff when documentation cannot resolve a request.

## Validate

```bash
uv pip install pytest
python -m pytest test_contracts.py -q
```

The tests use real ChromaDB and SQLite with deterministic embeddings and a scripted
model; they do not evaluate live embedding or model quality. See
[TEST_LOG.md](TEST_LOG.md) for the separate live API smoke test.
