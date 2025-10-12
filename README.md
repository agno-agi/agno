<div align="center" id="top">
  <a href="https://agno.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg">
      <img src="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg" alt="Agno">
    </picture>
  </a>
</div>
<div align="center">
  <h4>High-performance framework and runtime for multi-agent systems</h4>
</div>
<div align="center">
  <a href="https://docs.agno.com">📚 Documentation</a> &nbsp;|&nbsp;
  <a href="https://docs.agno.com/examples/introduction">💡 Examples</a> &nbsp;|&nbsp;
  <a href="https://www.agno.com/?utm_source=github&utm_medium=readme&utm_campaign=agno-github&utm_content=header">🏠 Website</a>
</div>

## What is Agno?

Agno is the fastest python framework for building agents with memory, knowledge, human in the loop and MCP support. You can put agents together as multi-agent teams or step-based agentic workflows.

Here’s an example of an Agent that connects to an MCP server, manages conversation history in a database, and is served using a FastAPI application that you can manage using the [AgentOS UI](https://os.agno.com).

```python agno_agent.py
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ************* Create Agent *************
agno_agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-5"),
    # Add a database to the Agent
    db=SqliteDb(db_file="agno.db"),
    # Add the Agno MCP server to the Agent
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
    # Add the previous session history to the context
    add_history_to_context=True,
    markdown=True,
)


# ************* Create AgentOS *************
agent_os = AgentOS(agents=[agno_agent])
# Get the FastAPI app for the AgentOS
app = agent_os.get_app()

# ************* Run AgentOS *************
if __name__ == "__main__":
    agent_os.serve(app="agno_agent:app", reload=True)
```

Agno's real advantage is its [AgentOS](https://docs.agno.com/agent-os/introduction) runtime:

1. You get a pre-built FastAPI app for running your agents, teams and workflows, meaning you start building your AI product on day one. This is a remarkable advantage over other solutions.
2. You also get a UI that connects directly to the pre-built FastAPI app. Use it to test, monitor and manage your system. This gives you unmatched visibility and control.
3. Your AgentOS runs in your cloud and you get complete privacy because no data ever leaves your system. This is incredible for security conscious enterprises that can't send data to external services.

Here's how the [AgentOS UI](https://os.agno.com) looks like:

https://github.com/user-attachments/assets/feb23db8-15cc-4e88-be7c-01a21a03ebf6

For organizations building agents, Agno provides the complete solution. You get the fastest framework for building agents (speed of development and execution), a pre-built FastAPI app that gets you building product on day one, and a control plane for managing your system.

## Getting started

If you're new to Agno, follow our [quickstart](https://docs.agno.com/introduction/quickstart) to build your first Agent and run it using the AgentOS.

After that, checkout the [examples gallery](https://docs.agno.com/examples/introduction) and build real-world applications with Agno.

## Documentation, Community & More Examples

- Docs: <a href="https://docs.agno.com" target="_blank" rel="noopener noreferrer">docs.agno.com</a>
- Cookbook: <a href="https://github.com/agno-agi/agno/tree/main/cookbook" target="_blank" rel="noopener noreferrer">Cookbook</a>
- Community forum: <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">community.agno.com</a>
- Discord: <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">discord</a>

## Setup Your Coding Agent to Use Agno

For LLMs and AI assistants to understand and navigate Agno's documentation, we provide an [llms.txt](https://docs.agno.com/llms.txt) or [llms-full.txt](https://docs.agno.com/llms-full.txt) file. This file is built for AI systems to efficiently parse and reference our documentation.

### IDE Integration

When building Agno agents, using Agno documentation as a source in your IDE is a great way to speed up your development. Here's how to integrate with Cursor:

1. In Cursor, go to the "Cursor Settings" menu.
2. Find the "Indexing & Docs" section.
3. Add `https://docs.agno.com/llms-full.txt` to the list of documentation URLs.
4. Save the changes.

Now, Cursor will have access to the Agno documentation. You can do the same with other IDEs like VSCode, Windsurf etc.

## Performance

If you're building with Agno, you're guaranteed best-in-class performance by default. Our obsession with performance is necessary because even simple AI workflows can spawn hundreds of Agents and because many tasks are long-running -- stateless, horizontal scalability is key for success.

At Agno, we optimize performance across 3 dimensions:

1. **Agent performance:** We optimize static operations (instantiation, memory footprint) and runtime operations (tool calls, memory updates, history management).
2. **System performance:** The AgentOS API is async by default and has a minimal memory footprint. The system is stateless and horizontally scalable, with a focus on preventing memory leaks. It handles parallel and batch embedding generation during knowledge ingestion, metrics collection in background tasks, and other system-level optimizations.
3. **Agent reliability and accuracy:** Monitored through evals, which we’ll explore later.

### Agent Performance

Let's measure the time it takes to instantiate an Agent and the memory footprint of an Agent. Here are the numbers (last measured in Oct 2025, on an Apple M4 MacBook Pro):

- **Agent instantiation:** ~3μs on average
- **Memory footprint:** ~6.6Kib on average

We'll show below that Agno Agents instantiate **529× faster than Langgraph**, **57× faster than PydanticAI**, and **70× faster than CrewAI**. Agno Agents also use **24× lower memory than Langgraph**, **4× lower than PydanticAI**, and **10× lower than CrewAI**.

> [!NOTE]
> Run time performance is bottlenecked by inference and hard to benchmark accurately, so we focus on minimizing overhead, reducing memory usage, and parallelizing tool calls.

### Instantiation Time

Let's measure instantiation time for an Agent with 1 tool. We'll run the evaluation 1000 times to get a baseline measurement. We'll compare Agno to LangGraph, CrewAI and Pydantic AI.

> [!NOTE]
> The code for this benchmark is available [here](https://github.com/agno-agi/agno/tree/main/cookbook/evals/performance). You should run the evaluation yourself on your own machine, please, do not take these results at face value.

```shell
# Setup virtual environment
./scripts/perf_setup.sh
source .venvs/perfenv/bin/activate

# Agno
python cookbook/evals/performance/instantiate_agent_with_tool.py

# LangGraph
python cookbook/evals/performance/comparison/langgraph_instantiation.py
# CrewAI
python cookbook/evals/performance/comparison/crewai_instantiation.py
# Pydantic AI
python cookbook/evals/performance/comparison/pydantic_ai_instantiation.py
```

LangGraph is on the right, **let's start it first and give it a head start**. Then CrewAI and Pydantic AI follow, and finally Agno. Agno obviously finishes first, but let's see by how much.

https://github.com/user-attachments/assets/54b98576-1859-4880-9f2d-15e1a426719d

### Memory Usage

To measure memory usage, we use the `tracemalloc` library. We first calculate a baseline memory usage by running an empty function, then run the Agent 1000x times and calculate the difference. This gives a (reasonably) isolated measurement of the memory usage of the Agent.

We recommend running the evaluation yourself on your own machine, and digging into the code to see how it works. If we've made a mistake, please let us know.

### Results

Taking Agno as the baseline, we can see that:

| Metric             | Agno | Langgraph   | PydanticAI | CrewAI     |
| ------------------ | ---- | ----------- | ---------- | ---------- |
| **Time (seconds)** | 1×   | 529× slower | 57× slower | 70× slower |
| **Memory (MiB)**   | 1×   | 24× higher  | 4× higher  | 10× higher |

Exact numbers from the benchmark:

| Metric             | Agno     | Langgraph | PydanticAI | CrewAI   |
| ------------------ | -------- | --------- | ---------- | -------- |
| **Time (seconds)** | 0.000003 | 0.001587  | 0.000170   | 0.000210 |
| **Memory (MiB)**   | 0.006642 | 0.161435  | 0.028712   | 0.065652 |

> [!NOTE]
> Agno agents are designed for performance and while we share benchmarks against other frameworks, we should be mindful that accuracy and reliability are more important than speed.

## Contributions

We welcome contributions, read our [contributing guide](https://github.com/agno-agi/agno/blob/v2.0/CONTRIBUTING.md) to get started.

## Telemetry

Agno logs which model an agent used so we can prioritize updates to the most popular providers. You can disable this by setting `AGNO_TELEMETRY=false` in your environment.

<p align="left">
  <a href="#top">⬆️ Back to Top</a>
</p>
