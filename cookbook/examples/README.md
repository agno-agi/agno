# Agno Examples

Small, complete agents and workflows to read, download, and adapt. Each directory has code,
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
| [Message Routing Agent](routing_agent) | Validate structured classifications and route customer messages |
| [Release Agent](release_agent) | Write release notes through an MCP tool |
| [Docs Agent](docs_agent) | Search and read documentation before answering with sources |
| [Task Agent](task_agent) | Let users act on their own product records |
| [Feedback Labeler](feedback_labeler) | Turn feedback into labeled records with review flags |
| [Analytics Agent](analytics_agent) | Explain active revenue with SQL and metric definitions |
| [Account Review](account_review) | Draft an account review and ask before saving it |

Personal Agent matches the [first-agent tutorial](https://docs.agno.com/first-agent).
Second Brain adds learning stores to that durable-notes pattern. Product Agent is
the runnable companion to [Agents as API](https://docs.agno.com/use-cases/agents-as-api).
Research and Support provide focused starting points for the broader
[Deep Research](https://docs.agno.com/use-cases/deep-research/overview) and
[Customer Support](https://docs.agno.com/use-cases/customer-support) guides.

## Use-case companions

Each introductory use case has a small runnable starting point:

| Documentation | Example |
| --- | --- |
| [Agents as API](https://docs.agno.com/use-cases/agents-as-api) | [Product Agent](product_agent) |
| [Structured Output as API](https://docs.agno.com/use-cases/structured-output-as-api) | [Message Routing Agent](routing_agent) |
| [Agents as MCP](https://docs.agno.com/use-cases/agents-as-mcp) | [Release Agent](release_agent) |
| [Docs Agent](https://docs.agno.com/use-cases/documentation-agents/overview) | [Docs Agent](docs_agent) |
| [Product Agent](https://docs.agno.com/use-cases/product-agents/overview) | [Task Agent](task_agent) |
| [Data Labeling](https://docs.agno.com/use-cases/data-labeling/overview) | [Feedback Labeler](feedback_labeler) |
| [Data & Analytics Agents](https://docs.agno.com/use-cases/data-agents/overview) | [Analytics Agent](analytics_agent) |
| [Workflow Automation](https://docs.agno.com/use-cases/workflow-automation) | [Account Review](account_review) |

These follow the introductory examples. The Docs Agent starter uses bundled
fictional Markdown pages to introduce search and reading before the full
application's indexing and synchronization. Later guides and deployment templates
add the surrounding infrastructure.

## Run an example

Change into the example directory, then:

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

Follow the directory's README for loading, seeding, server, or approval steps.
Product Agent and Message Routing call their running APIs; Release Agent calls
its running MCP service. Research and Support also have offline
`--fixture` demos. Tests are separate from interactive demos, with optional test
dependencies documented in each README.

Examples that retain conversations or workflow state use SQLite locally. The two brain MCP servers require JWT
verification; the other AgentOS starters are local services. Each README explains
storage and identity boundaries. The later
[deployment templates](https://docs.agno.com/deploy/introduction) provide the
path to a fully deployable codebase.

[Validation results](VALIDATION.md) distinguish package/source checks, fixture
contracts, live-model runs, and local HTTP/MCP tests.
