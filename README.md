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

## Introduction

[Agno](https://docs.agno.com) is a lightweight library for building Agents with memory, knowledge, tools and reasoning.

Developers use Agno to build Reasoning Agents, Multimodal Agents, Teams of Agents and Agentic Workflows. Agno also provides a beautiful UI to chat with Agents and tools to monitor and evaluate their performance.

Here's an Agent that researches and writes a report on a stock, reasoning through each step:

```python reasoning_finance_agent.py
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        ReasoningTools(add_instructions=True),
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True, company_news=True),
    ],
    instructions=[
        "Use tables to display data",
        "Only output the report, no other text",
    ],
    markdown=True,
)
agent.print_response("Write a report on NVDA", stream=True, show_full_reasoning=True, stream_intermediate_steps=True)
```

https://github.com/user-attachments/assets/bbb99955-9848-49a9-9732-3e19d77b2ff8

## Key features

Agno is simple, fast and model-agnostic. Here are some key features:

- **Model Agnostic**: Agno provides a unified interface to 23+ model providers, no lock-in.
- **Lightning Fast**: Agents instantiate in **~2μs** on average (10,000x faster than LangGraph) and use **~3.75Kib** memory on average (50x less than LangGraph) (see [benchmarks](#performance)).
- **Reasoning is a first class citizen**: Build Agents that can "think" and "analyze" using Reasoning Models, `ReasoningTools` or our custom `CoT+Tool-use` approach.
- **Natively Multi Modal**: Agno Agents are natively multi modal, they can take in text, image, audio and video and generate text, image, audio and video as output.
- **Advanced Multi Agent Architecture**: Agno provides an industry leading multi-agent architecture with 3 different modes: `route`, `collaborate` and `coordinate`.
- **Long-term Memory & Session Storage**: Agno provides `Storage` & `Memory` classes to provide your Agents with long-term memory and session storage.
- **20+ Vector Databases for Knowledge**: Add domain knowledge to your Agents by integrating with 20+ vector databases. **Fully async and highly performant.**
- **Structured Outputs**: Agno Agents have first class support for structured outputs using native structured outputs or `json_mode`.
- **Monitoring**: Monitor agent sessions and performance in real-time on [agno.com](https://app.agno.com).

## Building Agents with Agno

If you're new to Agno, start by building your [first Agent](https://docs.agno.com/introduction/agents), then chat with it on the [playground](https://docs.agno.com/introduction/playground) and finally, monitor it on [agno.com](https://docs.agno.com/introduction/monitoring).

After that, checkout the [Examples Gallery](https://docs.agno.com/examples) and build real-world applications with Agno.

## Installation

```shell
pip install -U agno
```

## What are Agents?

**Agents** are AI programs that operate autonomously.

- The **brain** of an Agent is the model that it uses to reason, execute, and respond to the user.
- The **body** of an Agent is the tools it uses to interact with the real world.
- The **behavior** of an Agent is defined by instructions; the better the model, the better it is at following instructions.

Agents also have **memory**, **knowledge**, **storage** and the ability to **reason**:

- **reasoning:** enables Agents to "think" before responding and "analyze" the results of their actions (i.e. tool calls), this improves the Agents' ability to solve problems that require sequential tool calls.
- **knowledge:** is domain-specific information the Agent can **_search on demand_** to make better decisions and provide accurate responses. Knowledge is stored in a vector database and this **_search on demand_** pattern is known as Agentic RAG.
- **storage:** is used by Agents to save session history and state in a database. Model APIs are stateless and storage enables us to continue conversations from where they left off. This makes Agents stateful, enabling multi-turn conversations.
- **memory:** gives Agents the ability to store and recall information from previous interactions, allowing them to learn user preferences and personalize their responses.

> Let's build a few Agents to see how they work.

## Example - Reasoning Agent

Let's start with a Reasoning Agent so we get a sense of Agno's capabilities.

Save this code to a file: `reasoning_agent.py`.

```python
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        ReasoningTools(add_instructions=True, add_few_shot=True),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions=[
        "Use tables to display data",
        "Only output the report, no other text",
    ],
    markdown=True,
)
agent.print_response(
    "Write a report on NVDA",
    stream=True,
    show_full_reasoning=True,
    stream_intermediate_steps=True,
)
```

Then create a virtual environment, install dependencies, export your `ANTHROPIC_API_KEY` and run the agent.

```shell
uv venv --python 3.12
source .venv/bin/activate

uv pip install agno anthropic yfinance

export ANTHROPIC_API_KEY=sk-ant-api03-xxxx

python reasoning_agent.py
```

We can see the Agent is reasoning through the task, using the `ReasoningTools` and `YFinanceTools` to gather information. This is how the output looks like:

https://github.com/user-attachments/assets/bbb99955-9848-49a9-9732-3e19d77b2ff8

> Now let's walk through the simple -> tools -> knowledge -> teams of agents flow.

## Example - Basic Agent

The simplest Agent is just an inference task, no tools, no memory, no knowledge.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    markdown=True
)
agent.print_response("Tell me about a breaking news story from New York.", stream=True)
```

To run the agent, install dependencies and export your `OPENAI_API_KEY`.

```shell
pip install agno openai

export OPENAI_API_KEY=sk-xxxx

python basic_agent.py
```

[View this example in the cookbook](./cookbook/getting_started/01_basic_agent.py)

## Example - Agent with tools

This basic agent will obviously make up a story, lets give it a tool to search the web.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True
)
agent.print_response("Tell me about a breaking news story from New York.", stream=True)
```

Install dependencies and run the Agent:

```shell
pip install duckduckgo-search

python agent_with_tools.py
```

Now you should see a much more relevant result.

[View this example in the cookbook](./cookbook/getting_started/02_agent_with_tools.py)

## Example - Agent with knowledge

Agents can store knowledge in a vector database and use it for RAG or dynamic few-shot learning.

**Agno agents use Agentic RAG** by default, which means they will search their knowledge base for the specific information they need to achieve their task.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.embedder.openai import OpenAIEmbedder
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.lancedb import LanceDb, SearchType

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a Thai cuisine expert!",
    instructions=[
        "Search your knowledge base for Thai recipes.",
        "If the question is better suited for the web, search the web to fill in gaps.",
        "Prefer the information in your knowledge base over the web results."
    ],
    knowledge=PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="recipes",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    ),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True
)

# Comment out after the knowledge base is loaded
if agent.knowledge is not None:
    agent.knowledge.load()

agent.print_response("How do I make chicken and galangal in coconut milk soup", stream=True)
agent.print_response("What is the history of Thai curry?", stream=True)
```

Install dependencies and run the Agent:

```shell
pip install lancedb tantivy pypdf duckduckgo-search

python agent_with_knowledge.py
```

[View this example in the cookbook](./cookbook/getting_started/03_agent_with_knowledge.py)

## Example - Multi Agent Teams

Agents work best when they have a singular purpose, a narrow scope and a small number of tools. When the number of tools grows beyond what the language model can handle or the tools belong to different categories, use a team of agents to spread the load.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.team import Team

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    show_tool_calls=True,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)],
    instructions="Use tables to display data",
    show_tool_calls=True,
    markdown=True,
)

agent_team = Team(
    mode="coordinate",
    members=[web_agent, finance_agent],
    model=OpenAIChat(id="gpt-4o"),
    success_criteria="A comprehensive financial news report with clear sections and data-driven insights.",
    instructions=["Always include sources", "Use tables to display data"],
    show_tool_calls=True,
    markdown=True,
)

agent_team.print_response("What's the market outlook and financial performance of AI semiconductor companies?", stream=True)
```

Install dependencies and run the Agent team:

```shell
pip install duckduckgo-search yfinance

python agent_team.py
```

[View this example in the cookbook](./cookbook/getting_started/05_agent_team.py)

## 🚨 Global Agent Hackathon! 🚨

We're thrilled to announce a month long, open source AI Agent Hackathon — open to all builders and dreamers working on agents, RAG, tool use, and multi-agent systems.

### 💰 Build something extordinary, win up to $20,000 in cash

We're giving away $20,000 in prizes for the most ambitious Agent projects

- 🏅 10 winners: $300 each
- 🥉 10 winners: $500 each
- 🥈 5 winners: $1,000 each
- 🥇 1 winner: $2,000
- 🏆 GRAND PRIZE: $5,000 🏆

> Follow this [post](https://www.agno.com/blog/agent-hackathon-april-2025) for more details and updates

### 🤝 Want to partner or judge?

If you're building in the AI Agent space, or want to help shape the next generation of Agent builders - we'd love to work with you.

Reach out to support@agno.com to get involved.

## Performance

At Agno, we're obsessed with performance. Why? because even simple AI workflows can spawn thousands of Agents to achieve their goals. Scale that to a modest number of users and performance becomes a bottleneck. Agno is designed to power high performance agentic systems:

- Agent instantiation: ~2μs on average (~10,000x faster than LangGraph).
- Memory footprint: ~3.75Kib on average (~50x less memory than LangGraph).

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

Dividing the average time of a Langgraph Agent by the average time of an Agno Agent:

```
0.020526s / 0.000002s ~ 10,263
```

In this particular run, **Agno Agents startup is roughly 10,000 times faster than Langgraph Agents**. The numbers continue to favor Agno as the number of tools grow, and we add memory and knowledge stores.

### Memory usage

To measure memory usage, we use the `tracemalloc` library. We first calculate a baseline memory usage by running an empty function, then run the Agent 1000x times and calculate the difference. This gives a (reasonably) isolated measurement of the memory usage of the Agent.

We recommend running the evaluation yourself on your own machine, and digging into the code to see how it works. If we've made a mistake, please let us know.

Dividing the average memory usage of a Langgraph Agent by the average memory usage of an Agno Agent:

```
0.137273/0.002528 ~ 54.3
```

**Langgraph Agents use ~50x more memory than Agno Agents**. In our opinion, memory usage is a much more important metric than instantiation time. As we start running thousands of Agents in production, these numbers directly start affecting the cost of running the Agents.

### Conclusion

Agno agents are designed for performance and while we do share some benchmarks against other frameworks, we should be mindful that accuracy and reliability are more important than speed.

We'll be publishing accuracy and reliability benchmarks running on Github actions in the coming weeks. Given that each framework is different and we won't be able to tune their performance like we do with Agno, for future benchmarks we'll only be comparing against ourselves.

## Cursor Setup

When building Agno agents, using Agno documentation as a source in Cursor is a great way to speed up your development.

1. In Cursor, go to the settings or preferences section.
2. Find the section to manage documentation sources.
3. Add `https://docs.agno.com` to the list of documentation URLs.
4. Save the changes.

Now, Cursor will have access to the Agno documentation.

## Documentation, Community & More examples

- Docs: <a href="https://docs.agno.com" target="_blank" rel="noopener noreferrer">docs.agno.com</a>
- Getting Started Examples: <a href="https://github.com/agno-agi/agno/tree/main/cookbook/getting_started" target="_blank" rel="noopener noreferrer">Getting Started Cookbook</a>
- All Examples: <a href="https://github.com/agno-agi/agno/tree/main/cookbook" target="_blank" rel="noopener noreferrer">Cookbook</a>
- Community forum: <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">community.agno.com</a>
- Chat: <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">discord</a>

## Contributions

We welcome contributions, read our [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md) to get started.

## Telemetry

Agno logs which model an agent used so we can prioritize updates to the most popular providers. You can disable this by setting `AGNO_TELEMETRY=false` in your environment.

<p align="left">
  <a href="#top">⬆️ Back to Top</a>
</p>
