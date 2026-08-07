# Knowledge

AgentOS turns a `Knowledge` instance into an operational HTTP surface for
content management and semantic search. This lesson serves one local knowledge
base, shares it with an agent, and closes the full REST lifecycle rather than
stopping at application construction.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Serve one SQLite- and Chroma-backed knowledge base shared with an agent. |
| `rest_api_knowledge.py` | Upload, poll, list, search, delete, and verify knowledge content over HTTP. |

## Prerequisites

Set `OPENAI_API_KEY`. The server uses `text-embedding-3-small` when it seeds and
uploads content, and its served agent uses OpenAI Responses `gpt-5.5`.
SQLite stores content metadata in `tmp/knowledge.db`; Chroma stores vectors
under `tmp/knowledge_chroma`.

## Run

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/10_knowledge/basic.py
```

In another terminal, run the lifecycle client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/10_knowledge/rest_api_knowledge.py
```

The client first verifies `/health` and `/config`, then uses only concrete
knowledge routes:

1. `POST /knowledge/content` accepts form data and returns `202`.
2. `GET /knowledge/content/{content_id}/status` reports background processing.
3. `GET /knowledge/content` lists the stored item in a `{data, meta}` envelope.
4. `POST /knowledge/search` searches the vector store with a JSON body.
5. `DELETE /knowledge/content/{content_id}` removes the item, and a final
   `GET /knowledge/content/{content_id}` returns `404`.

Because this AgentOS exposes exactly one knowledge base, `db_id` and
`knowledge_id` are optional on these calls. Applications serving multiple
knowledge bases must select one with those identifiers.
