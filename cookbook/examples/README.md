# Agno Examples

Small, complete agents to read, download, and adapt. Each directory has an agent,
a demo, a README, and a `requirements.txt`. Start with a working example; move to
a deployable template when you need the surrounding application infrastructure.

| Example | Useful job |
| --- | --- |
| [Personal Agent](personal_agent) | Keep projects, tasks, and decisions in durable notes |
| [Second Brain](second_brain) | Learn preferences and facts about people and projects across conversations |
| [Team Brain](team_brain) | Share decisions with their reasoning and verified authorship |
| [Product Agent](product_agent) | Serve product knowledge over HTTP with sessions and streaming |
| [Research Agent](research_agent) | Investigate a focused question and save a cited brief |
| [Support Agent](support_agent) | Answer from maintained docs and prepare a local handoff when evidence is missing |

Personal Agent matches the [first-agent tutorial](https://docs.agno.com/first-agent).
Second Brain adds learning stores to that durable-notes pattern. Product Agent is
the runnable companion to [Agents as API](https://docs.agno.com/use-cases/agents-as-api).
Research and Support provide focused starting points for the broader
[Deep Research](https://docs.agno.com/use-cases/deep-research/overview) and
[Customer Support](https://docs.agno.com/use-cases/customer-support) guides.

## Run an example

Change into the example directory, then:

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

Follow the directory's README for any initial loading or server steps. Product
Agent's demo calls its running API. Research and Support also have offline
`--fixture` demos. Tests are separate from interactive demos, with optional test
dependencies documented in each README.

The examples use SQLite locally. The two brain MCP servers require JWT
verification; the other AgentOS starters are local services. Each README explains
storage and identity boundaries. The later
[deployment templates](https://docs.agno.com/deploy/introduction) provide the
path to a fully deployable codebase.

[Validation results](VALIDATION.md) distinguish package/source checks, fixture
contracts, live-model runs, and local HTTP/MCP tests.
