# Support Agent

Answer Lantern product questions from maintained documentation and return a structured handoff when the documentation is insufficient. Lantern is fictional.

## Run locally

From the repository root:

```bash
cd cookbook/examples/support_agent
uv sync --locked
export OPENAI_API_KEY="your-openai-api-key"
uv run --no-sync demo.py
```

Each directory is a standalone uv project; a downloaded directory uses the same
commands after changing into it. `.env.example` is a template and is not loaded
automatically. Export variables explicitly. The lock pins published Agno 3.0.8;
Python 3.12 or newer is required. Model calls use `openai:gpt-5.6`.

## What to try

The demo asks how to export a Lantern workspace, then "Can a member do that too?"
in the same conversation. Expect an answer sourced to `docs/exports.md` and a
follow-up explaining that only owners/admins can export. It then asks for a
Germany data residency guarantee under a custom contract, which these documents
do not establish. Expect an acknowledged gap and a `needs_human` response.

```bash
uv run --no-sync demo.py --fixture
uv run --no-sync support_agent.py
```

`--fixture` scripts the model responses but executes the actual Agno knowledge
retriever, reference tracking, history, output parsing, and session persistence.
It is an offline contract demonstration, not a model accuracy evaluation.
AgentOS listens on `http://127.0.0.1:7777`; use `/docs` for the API. This service is
for trusted local use and does not configure remote authentication.

## Knowledge, handoffs, and persistence

The maintained fictional corpus is in `docs/`: exports, membership, and plans.
Edit those Markdown files to maintain it; retrieval reads the current files on
every search, so there is no stale embedding index. A short keyword-overlap
retriever plugs into Agno's `knowledge_retriever` API and returns content plus
source metadata. The agent rewrites follow-up searches with the prior topic.
This small lexical search can miss paraphrases; an empty search is not proof that
an answer is absent from a larger corpus.

Agno records retrieved documents in `RunOutput.references`. The demo verifies
that cited paths were retrieved on that turn. An unsupported response returns a
structured handoff containing the question, relevant conversation context, and
unresolved issues. The demo saves it to `tmp/handoff-<run-id>.json`. No ticket is
opened and nobody is contacted. Relevant documentation and conversation context
are sent to the model provider.

`tmp/support_agent.db` holds sessions and results, including references and
handoffs. Reuse both user ID and session ID for follow-ups; the last three runs
are included as history. New sessions start new conversations. Caller-supplied
IDs are local labels and are not an authentication boundary on this starter.

## Extend it

Replace the fictional docs with a maintained product corpus. For a larger corpus,
use Agno Knowledge with a vector database and preserve source metadata. Add human
review before connecting handoffs to an external ticket system.

## Validate

From this example directory:

```bash
uv run --no-sync pytest test_contracts.py -q
```

See [TEST_LOG.md](TEST_LOG.md) for measured results and limitations. To check the
checkout instead of the published package, prefix the command with
`PYTHONPATH=../../../libs/agno` while running from this directory. The source
revision is recorded in the collection's [validation report](../VALIDATION.md).
