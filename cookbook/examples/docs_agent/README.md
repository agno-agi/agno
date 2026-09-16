# Docs Agent

Answer documentation questions by searching and reading complete pages.
A small runnable companion to [Docs Agent](https://docs.agno.com/use-cases/documentation-agents/overview).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/docs_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

The demo asks about filtered exports, follows up about scheduled CSV delivery,
and asks an undocumented data-residency question. Expect links to the bundled
Markdown sources, a distinction between emailed report links and CSV attachments,
and an explicit evidence gap for data residency.

`docs/` contains fictional Acme Reports pages. Replace them with a small set of
your own Markdown pages. Search uses keyword overlap, and `read_doc` accepts only
listed page paths. Citations open local files when viewed in this directory;
the API does not serve those Markdown files. The tools read current files on
every call. SQLite stores conversations in `docs-agent.db`.

Run `python docs_agent.py` for a local AgentOS API at `http://localhost:7777`.
For a larger corpus, the [Docs Agent application](https://github.com/agno-agi/docs-agent)
adds published-page retrieval, indexing, synchronization, MCP, and deployment.
This starter illustrates the search/read/answer flow without that infrastructure.

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
