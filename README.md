<div align="center" id="top">
  <a href="https://docs-v2.agno.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg">
      <img src="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg" alt="Agno">
    </picture>
  </a>
</div>
<div align="center">
  <a href="https://docs-v2.agno.com">📚 Documentation</a> &nbsp;|&nbsp;
  <a href="https://docs-v2.agno.com/examples/introduction">💡 Examples</a> &nbsp;|&nbsp;
  <a href="https://github.com/agno-agi/agno/stargazers">🌟 Star Us</a>
</div>

## What is Agno?

[Agno](https://docs.agno.com) is a high-performance runtime for multi-agent systems. Use it to build, run and manage secure agent systems in your cloud.

**Agno gives you:**

1. The fastest framework for building agents, multi-agent teams and agentic workflows.
2. A high-performance runtime for your agents, teams and workflows called the AgentOS.
3. A powerful platform for testing, monitoring and managing your agent system.

### Example: Reasoning Agent that uses the DuckDuckGo API to answer questions:

```python reasoning_web_search_agent.py
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.tools.duckduckgo import DuckDuckGoTools

reasoning_agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[
        ReasoningTools(add_instructions=True),
        DuckDuckGoTools(),
    ],
    instructions="Search the web for information",
    markdown=True,
)
```

## Get Started

If you're new to Agno, read the documentation to build your [first Agent](https://docs-v2.agno.com/introduction/first-agent) and interact with it on [AgentOS](https://docs-v2.agno.com/agent-os/introduction).

After that, checkout the [Examples Gallery](https://docs-v2.agno.com/examples) and build real-world applications with Agno.


## Why Agno?

Agno will help you build best-in-class, highly-performant agentic systems, saving you hours of research and boilerplate. Here are some key features that set Agno apart:

- **Model Agnostic**: Agno provides a unified interface to 25+ model providers, no lock-in.
- **Highly performant**: Agents instantiate in **~3μs** and use **~6.5Kib** memory on average.
- **Reasoning is a first class citizen**: Reasoning improves reliability and is a must-have for complex autonomous agents. Agno supports 3 approaches to reasoning: Reasoning Models, `ReasoningTools` or our custom `chain-of-thought` approach.
- **Natively Multi-Modal**: Agno Agents are natively multi-modal, they accept text, image, audio and video as input and generate text, image, audio and video as output.
- **Advanced Multi-Agent Architecture**: Agno provides an industry leading multi-agent architecture (**Agent Teams**) with reasoning, memory, and shared context.
- **Built-in Agentic Search**: Agents can search for information at runtime using 20+ vector databases. Agno provides state-of-the-art Agentic RAG, **fully async and highly performant.**
- **Built-in Memory & Session Storage**: Agents come with built-in `Storage` & `Memory` drivers that give your Agents long-term memory and session storage.
- **Structured Outputs**: Agno Agents can return fully-typed responses using model provided structured outputs or `json_mode`.
- **Pre-built FastAPI Routes**: After building your Agents, serve them using pre-built FastAPI routes. 0 to production in minutes.
- **Monitoring**: Monitor agent sessions and performance in real-time on [agno.com](https://app.agno.com).

## Installation

```shell
pip install -U agno
```

## Example - Documentation Support Agent

Let's build a Reasoning Agent to get a sense of Agno's capabilities.

Save this code to a file: `documentation_support_agent.py`.

```python
import asyncio
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.tools.mcp import MCPTools

async def run_agent(message: str) -> None:
  agno_tools = MCPTools(
    transport="streamable-http",
    # You can use any MCP server you want
    url="https://docs-v2.agno.com/mcp"
  )
  await agno_tools.connect()

  agent = Agent(
      model=Claude(id="claude-sonnet-4-20250514"),
      tools=[
          ReasoningTools(add_instructions=True),
          agno_tools,
      ],
      instructions=[
          "Use tables to display data",
          "Only output the report, no other text",
      ],
      markdown=True,
  )
  await agent.aprint_response(
      message,
      stream=True,
      show_full_reasoning=True,
      stream_intermediate_steps=True,
  )

  await agno_tools.close()

if __name__ == "__main__":
  asyncio.run(run_agent("What is AgentOS and how can I use it?"))
```

Then create a virtual environment, install dependencies, export your `ANTHROPIC_API_KEY` and run the agent.

```shell
uv venv --python 3.12
source .venv/bin/activate

uv pip install agno anthropic

export ANTHROPIC_API_KEY=sk-ant-api03-xxxx

python documentation_support_agent.py
```

We can see the Agent is reasoning through the task, using the `ReasoningTools` and `MCPTools` to gather information. 

## Example - Multi Agent Teams

Agents are the atomic unit of work, and work best when they have a narrow scope and a small number of tools. When the number of tools grows beyond what the model can handle or you need to handle multiple concepts, use a team of agents to spread the load.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.team import Team

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-5-nano"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    markdown=True,
)

hackernews_agent = Agent(
    name="HackerNews Agent",
    role="Get top stories from hackernews",
    model=OpenAIChat(id="gpt-5-nano"),
    tools=[HackerNewsTools()],

    markdown=True,
)

agent_team = Team(
    mode="coordinate",
    members=[web_agent, hackernews_agent],
    model=OpenAIChat(id="gpt-5-nano"),
    instructions=["Always include sources", "Use tables to display data"],

    markdown=True,
)

agent_team.print_response("What's the market outlook and financial performance of AI semiconductor companies?", stream=True)
```

Install dependencies and run the Agent team:

```shell
pip install ddgs

python agent_team.py
```

[View another example in this cookbook](./cookbook/getting_started/17_agent_team.py)

## Performance

At Agno, we're obsessed with performance. Why? because even simple AI workflows can spawn thousands of Agents. Scale that to a modest number of users and performance becomes a bottleneck. Agno is designed for building high performance agentic systems:

- Agent instantiation: ~3μs on average
- Memory footprint: ~6.5Kib on average

> Tested on an Apple M4 Mackbook Pro.

While an Agent's run-time is bottlenecked by inference, we must do everything possible to minimize execution time, reduce memory usage, and parallelize tool calls. These numbers may seem trivial at first, but our experience shows that they add up even at a reasonably small scale.

### Instantiation time

Let's measure the time it takes for an Agent with 1 tool to start up. We'll run the evaluation 1000 times to get a baseline measurement.

You should run the evaluation yourself on your own machine, please, do not take these results at face value.

```shell
# Setup virtual environment
./scripts/perf_setup.sh
source .venvs/perfenv/bin/activate
# OR Install dependencies manually
# pip install openai agno langgraph langchain_openai

# Agno
python evals/performance/instantiation_with_tool.py

# LangGraph
python evals/performance/other/langgraph_instantiation.py
```

> The following evaluation is run on an Apple M4 Mackbook Pro. It also runs as a Github action on this repo.

LangGraph is on the right, **let's start it first and give it a head start**.

Agno is on the left, notice how it finishes before LangGraph gets 1/2 way through the runtime measurement, and hasn't even started the memory measurement. That's how fast Agno is.

https://github.com/user-attachments/assets/ba466d45-75dd-45ac-917b-0a56c5742e23

### Memory usage

To measure memory usage, we use the `tracemalloc` library. We first calculate a baseline memory usage by running an empty function, then run the Agent 1000x times and calculate the difference. This gives a (reasonably) isolated measurement of the memory usage of the Agent.

We recommend running the evaluation yourself on your own machine, and digging into the code to see how it works. If we've made a mistake, please let us know.

### Conclusion

Agno agents are designed for performance and while we do share some benchmarks against other frameworks, we should be mindful that accuracy and reliability are more important than speed.

Given that each framework is different and we won't be able to tune their performance like we do with Agno, for future benchmarks we'll only be comparing against ourselves.

## Complete Documentation Index

For LLMs and AI assistants to understand and navigate Agno's complete documentation, we provide an [LLMs.txt](https://docs-v2.agno.com/llms.txt) or [LLMs-Full.txt](https://docs-v2.agno.com/llms-full.txt) file.

This file is specifically formatted for AI systems to efficiently parse and reference our documentation.

### Cursor Setup

When building Agno agents, using Agno documentation as a source in Cursor is a great way to speed up your development.

1. In Cursor, go to the "Cursor Settings" menu.
2. Find the "Indexing & Docs" section.
3. Add `https://docs-v2.agno.com/llms-full.txt` to the list of documentation URLs.
4. Save the changes.

Now, Cursor will have access to the Agno documentation.

## Documentation, Community & More examples

- Docs: <a href="https://docs-v2.agno.com" target="_blank" rel="noopener noreferrer">docs-v2.agno.com</a>
- Cookbook: <a href="https://github.com/agno-agi/agno/tree/v2.0/cookbook" target="_blank" rel="noopener noreferrer">Cookbook</a>
- Community forum: <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">community.agno.com</a>
- Discord: <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">discord</a>

## Contributions

We welcome contributions, read our [contributing guide](https://github.com/agno-agi/agno/blob/v2.0/CONTRIBUTING.md) to get started.

## Telemetry

Agno logs which model an agent used so we can prioritize updates to the most popular providers. You can disable this by setting `AGNO_TELEMETRY=false` in your environment.

<p align="left">
  <a href="#top">⬆️ Back to Top</a>
</p>
