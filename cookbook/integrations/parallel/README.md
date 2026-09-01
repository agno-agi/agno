# Parallel

Build web-research agents on [Parallel](https://parallel.ai) with Agno.

Parallel offers APIs built for agents:

| API | Speed | Use Case |
|-----|-------|----------|
| **Search** | 1-5s | Quick lookups, gather sources for an answer |
| **Extract** | 1-5s | Clean text from specific URLs (incl. JS pages and PDFs) |
| **Task** | 10s-25min | Deep research with structured output and citations |
| **Monitor** | Scheduled | Track topics over time, detect changes |

## Cookbooks

A progression from a single agent to a deployable research app:

| File | Focus |
|------|-------|
| [`01_quickstart.py`](./01_quickstart.py) | Minimal research agent (Search) |
| [`02_extract_content.py`](./02_extract_content.py) | Read specific URLs with the Extract API |
| [`03_deep_research.py`](./03_deep_research.py) | Cited reports with the Task API |
| [`04_research_assistant.py`](./04_research_assistant.py) | Persistent assistant (DB, session, memory) using every agent API |
| [`05_web_plus_knowledge.py`](./05_web_plus_knowledge.py) | Hybrid: Parallel live web + Agno Knowledge (vector RAG) |
| [`06_research_team.py`](./06_research_team.py) | A Team of Parallel-backed agents |
| [`07_research_workflow.py`](./07_research_workflow.py) | A deterministic gather-then-synthesize pipeline |
| [`08_competitive_intel_monitor.py`](./08_competitive_intel_monitor.py) | Monitor API as a standing intelligence desk |
| [`09_agent_os_app.py`](./09_agent_os_app.py) | Deploy a research agent as an AgentOS app |

> Looking for the tool-by-tool reference (one example per API and use case)?
> See [`cookbook/91_tools/parallel`](../../91_tools/parallel/).

## Setup

```bash
pip install parallel-web
export PARALLEL_API_KEY=<your-api-key>
```

Some examples need extra packages: `05_web_plus_knowledge.py` uses `chromadb`
for the local vector store.

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools()],          # Search + Extract by default
)
agent.print_response("What did Parallel launch most recently?", stream=True)
```

Enable the deeper APIs with flags:

```python
ParallelTools(enable_task=True)       # deep research with citations
ParallelTools(enable_monitor=True)    # track topics over time
```

## Running Examples

```bash
.venvs/demo/bin/python cookbook/integrations/parallel/<file>.py
```
