<div align="center" id="top">
  <a href="https://docs.agno.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg">
      <img src="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg" alt="Agno">
    </picture>
  </a>
</div>
<div align="center">
  <a href="https://docs.agno.com">📚 Documentation</a> &nbsp;|&nbsp;
  <a href="https://docs.agno.com/examples/introduction">💡 Examples</a> &nbsp;|&nbsp;
  <a href="https://github.com/agno-agi/agno/stargazers">🌟 Star Us</a>
</div>

## What is Agno?

[Agno](https://docs.agno.com) is a high-performance runtime for multi-agent systems. Use it to build, run and manage secure agent systems in your cloud.

**Agno gives you:**

1. The fastest framework for building agents and multi-agent workflows.
2. A high-performance runtime for your multi-agent systems called the AgentOS.
3. Built-in session management, memory, knowledge, human in the loop and MCP support.
4. SSE compatible API endpoints for building your agentic product.
5. A powerful platform for monitoring and managing your AgentOS.

### Example

In 10 lines of code, we can build an Agent that will fetch the top stories from HackerNews and summarize them.

```python hackernews_agent.py
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.hackernews import HackerNewsTools

agent = Agent(
    model=Claude(id="claude-sonnet-4-0"),
    tools=[HackerNewsTools()],
    markdown=True,
)
agent.print_response("Summarize the top 5 stories on hackernews", stream=True)
```

## Get Started

If you're new to Agno, start by [building your first Agent](/introduction/first-agent) and run it using the AgentOS.

After that, checkout the [Examples Gallery](https://docs.agno.com/examples) and build real-world applications with Agno.

## Setup your coding agent to use Agno

For LLMs and AI assistants to understand and navigate Agno's documentation, we provide an [LLMs.txt](https://docs.agno.com/llms.txt) or [LLMs-Full.txt](https://docs.agno.com/llms-full.txt) file.

This file is specifically formatted for AI systems to efficiently parse and reference our documentation.

### Cursor Setup

When building Agno agents, using Agno documentation as a source in Cursor is a great way to speed up your development.

1. In Cursor, go to the "Cursor Settings" menu.
2. Find the "Indexing & Docs" section.
3. Add `https://docs.agno.com/llms-full.txt` to the list of documentation URLs.
4. Save the changes.

Now, Cursor will have access to the Agno documentation.

### Agno MCP Server

You can also also add the Agno MCP server to your Agent to query and search the Agno documentation. Add [http://docs.agno.com/mcp](http://docs.agno.com/mcp) to your Agent's tools.

## Documentation, Community & More examples

- Docs: <a href="https://docs.agno.com" target="_blank" rel="noopener noreferrer">docs.agno.com</a>
- Cookbook: <a href="https://github.com/agno-agi/agno/tree/main/cookbook" target="_blank" rel="noopener noreferrer">Cookbook</a>
- Community forum: <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">community.agno.com</a>
- Discord: <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">discord</a>

## Why Agno?

AI engineering is a systems problem (infrastructure, software, context, security) and Agno is the only framework that delivers a complete solution with a delightful developer experience.

You get the fastest framework for building agents with out of the box session management, memory, knowledge, human in the loop and MCP support, this helps you build and iterate quickly.

But to be honest, you can probably get there using other frameworks or rolling your own, it'll take extra effort and your code won't be as performant, but you'll get there.

The real advantage of Agno is the AgentOS runtime:

1. You get a FastAPI app with pre-built API endpoints, meaning you get started with building your product on day one. This is a remarkable advantage over other solutions.
2. You get a control plane which connects directly to the FastAPI app for testing, monitoring and managing your agentic system. This gives you unmatched control over your system.
3. Your AgentOS runs in your cloud and you get complete data control because no data ever leaves your system. This is incredible for security conscious enterprises.

With Agno, you can build your agents, ship them to production with a pre-built FastAPI app, scale it horizontally and keep your data private and secure. If your goal is to build your product as quickly as possible, Agno get's you there while delivering the best developer experience.

If you're an enterprise that's worried about data privacy and security, Agno is the only framework that gives you complete control over your data. Your AgentOS runs securely in your cloud, what could be more private than that?

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

## Contributions

We welcome contributions, read our [contributing guide](https://github.com/agno-agi/agno/blob/v2.0/CONTRIBUTING.md) to get started.

## Telemetry

Agno logs which model an agent used so we can prioritize updates to the most popular providers. You can disable this by setting `AGNO_TELEMETRY=false` in your environment.

<p align="left">
  <a href="#top">⬆️ Back to Top</a>
</p>
