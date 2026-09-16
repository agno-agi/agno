# Research Agent

Investigate a focused question and save a brief with findings, inspected source links, uncertainty, and open questions.

## Run locally

From the repository root:

```bash
cd cookbook/examples/research_agent
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

## Fixture and live modes

The default question is "Should a small public library pilot a monthly repair
cafe?" Default `RESEARCH_MODE=fixture` uses two explicitly fictional source pages
from `sources.json` and a live OpenAI model. It illustrates how differing pilot
and survey evidence leads to a qualified recommendation.

For a completely offline, deterministic run with scripted model responses:

```bash
python demo.py --fixture
```

The same Agent executes search and read tools, parses its output schema, and
persists its run. This is a **fixture demonstration**, not evidence of live search
quality or model citation accuracy. The saved artifact labels both source mode
and whether the model was scripted.

For real web research:

```bash
RESEARCH_MODE=live python demo.py
RESEARCH_MODE=live python research_agent.py
```

Live search uses Agno's `WebSearchTools` (DDGS) and `WebsiteTools` to read pages;
the project declares their dependencies. No additional API key is required.
Search services can throttle requests; pages may be inaccessible. The tools report
unreadable evidence instead of counting empty content as inspected. Do not cite
search snippets. Reading is restricted to URLs returned by discovery.

## Results and boundaries

`demo.py` checks that every finding cites an inspected URL, then saves
`tmp/brief-<run-id>.json` with findings, uncertainty, open questions, and the exact
inspected-source set. These checks establish provenance, not that each claim is
entailed by its citation; review the actual evidence. Retrieved text is untrusted
data, and the agent is instructed not to follow embedded instructions.

Runs persist in `tmp/research_agent.db`; each demo starts a fresh session. The
AgentOS path listens on `http://127.0.0.1:7777`; `/docs` exposes the API. API runs
return a structured brief and persist it with the session; `demo.py` also exports
it to JSON. This is a trusted local service with no remote authentication setup.
Queries and relevant retrieved material go to the model provider; live search
queries and page requests also reach those services.

## Extend it

Adapt the question in `demo.py`, or restrict live discovery to a curated set of
publishers. Review source quality and any disagreement before sharing a brief.

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
