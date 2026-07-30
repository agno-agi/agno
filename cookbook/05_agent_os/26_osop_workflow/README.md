# Research Agent Workflow — OSOP Example

This folder shows how to express an **Agno agent pattern** as a portable
[OSOP](https://github.com/Archie0125/osop-spec) workflow, and how to run the
same workflow with Agno.

## What is OSOP?

**OSOP** (Open Standard Operating Process) is a YAML-based format for
describing multi-step workflows in a tool-agnostic way. Think of it as the
*OpenAPI of workflows*: a single `.osop` file says what your agent does, so
teams can share, review, and port agent workflows across frameworks (Agno,
LangChain, CrewAI, …).

An OSOP file has two parts:

- **`nodes`** — the steps. Core node types: `agent`, `api`, `cli`, `human`.
- **`edges`** — the connections. Core edge modes: `sequential`,
  `conditional`, `parallel`, `fallback`.

## What's in this folder

| File | Purpose |
|------|---------|
| `research_workflow.osop` | The portable OSOP definition of a research agent. |
| `research_workflow.py` | The runnable Agno implementation of the same workflow. |

## The workflow

| OSOP Node | OSOP Type | Agno Equivalent |
|-----------|-----------|-----------------|
| user-request | `human` | The message you type in the UI/API |
| web-search | `agent` | `Agent(tools=[DuckDuckGoTools()])` |
| analyze | `agent` | `Agent` with analysis instructions |
| generate-report | `agent` | `Agent` with report instructions |
| deliver | `api` | Output returned to the user |

Each OSOP `agent` node becomes an `Agent`; the `sequential` edges become
ordered `Step`s inside a `Workflow`; the whole graph is served by `AgentOS`.

## Run the Agno version

```bash
# 1. Set your key
export OPENAI_API_KEY=sk-...

# 2. Install dependencies
pip install agno duckduckgo-search openai sqlalchemy fastapi python-multipart

# 3. Run
python cookbook/05_agent_os/26_osop_workflow/research_workflow.py
