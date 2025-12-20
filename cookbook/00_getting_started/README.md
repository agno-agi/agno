# Getting Started with Agents, The Easy Way

This guide walks through the basics of building Agents, the easy way. Follow along to learn how to build agents with tools, storage, memory, knowledge, and state. You'll also learn how to build multi-agent teams and step-based agentic workflows.

We recommend running the examples in order, as each example builds on the previous, introducing new concepts and capabilities progressively. Examples contain detailed comments and example prompts to help you understand what's happening.

All examples use **Gemini 3 Flash** — fast, affordable, and excellent at tool calling. But Agno is model-agnostic and you can swap in any provider with a one line change.

## Cookbooks

| # | Cookbook | What You'll Learn | Key Features |
|:--|:---------|:------------------|:-------------|
| 01 | `agent_with_tools.py` | Give an agent tools to fetch real-time data | Tool Calling, Data Fetching |
| 02 | `agent_with_storage.py` | Persist conversations across runs | Persistent Storage, Session Management |
| 03 | `agent_search_over_knowledge.py` | Load documents into a knowledge base and search with hybrid search | Chunking, Embedding, Hybrid Search, Agentic RAG |
| 04 | `custom_tool_for_self_learning.py` | How to write your own tools and use them in an agent | Custom Tools, Self-Learning |
| 05 | `agent_with_structured_output.py` | Return typed Pydantic models | Structured Output, Type Safety |
| 06 | `agent_with_typed_input_output.py` | Full type safety on both ends | Input Schema, Output Schema |
| 07 | `agent_with_memory.py` | Remember user preferences across sessions | Memory Manager, Personalization, User Memory |
| 08 | `agent_with_state_management.py` | Track, modify, and persist structured state | Session State, State Management |
| 09 | `multi_agent_team.py` | Coordinate multiple agents by organizing them into a team | Dynamic Collaboration, Multi-Agent Team, Team Leader |
| 10 | `sequential_workflow.py` | Chain agents in a pipeline | Agentic Workflow, Predictable Execution, Pipelines |

## Key Concepts

| Concept | What It Does | When to Use |
|:--------|:-------------|:------------|
| **Tools** | Let agents take actions | Fetch data, call APIs, run code |
| **Storage** | Persist conversation history | Multi-turn conversations and state management |
| **Knowledge** | Searchable document store | RAG, documentation Q&A |
| **Memory** | Remember user preferences | Personalization |
| **State** | Structured data the agent manages | Tracking progress, managing lists |
| **Teams** | Multiple agents collaborating | Dynamic collaboration of specialized agents |
| **Workflows** | Sequential agent pipelines | Predictable multi-step processes and data flow |

## Why Gemini 3 Flash?

- **Speed** — Sub-second responses make agent loops feel responsive
- **Tool Calling** — Reliable function calling out of the box
- **Affordable** — Cheap enough to experiment freely

Agno is **Model-Agnostic** and you can swap to OpenAI, Anthropic, or any provider with one line.

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate a virtual environment

```bash
uv venv .getting-started --python 3.12
source .getting-started/bin/activate
```

### 3. Install dependencies

```bash
uv pip install -r cookbook/00_getting_started/requirements.txt
```

### 4. Set your API key

```bash
export GOOGLE_API_KEY=your-google-api-key
```

### 5. Run any cookbook

```bash
python cookbook/00_getting_started/agent_with_tools.py
```

**That's it.** No Docker, no Postgres — just Python and an API key.

---

## Run via Agent OS

Agent OS provides a web interface for interacting with your agents. Start the server:

```bash
python cookbook/00_getting_started/run.py
```

Then visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an endpoint.

---

## Run Cookbooks Individually

```bash
# 01 - Tools: Fetch real market data
python cookbook/00_getting_started/agent_with_tools.py

# 02 - Storage: Remember conversations
python cookbook/00_getting_started/agent_with_storage.py

# 03 - Knowledge: Search your documents
python cookbook/00_getting_started/agent_search_over_knowledge.py

# 04 - Custom Tools: Write your own
python cookbook/00_getting_started/custom_tool_for_self_learning.py

# 05 - Structured Output: Get typed responses
python cookbook/00_getting_started/agent_with_structured_output.py

# 06 - Typed I/O: Full type safety
python cookbook/00_getting_started/agent_with_typed_input_output.py

# 07 - Memory: Remember user preferences
python cookbook/00_getting_started/agent_with_memory.py

# 08 - State: Manage watchlists
python cookbook/00_getting_started/agent_with_state_management.py

# 09 - Teams: Bull vs Bear analysis
python cookbook/00_getting_started/multi_agent_team.py

# 10 - Workflows: Research pipeline
python cookbook/00_getting_started/sequential_workflow.py
```

## File Structure

```
cookbook/00_getting_started/
├── agent_with_tools.py                 # Tools and data fetching
├── agent_with_storage.py               # Conversation persistence
├── agent_search_over_knowledge.py      # Knowledge base + hybrid search
├── custom_tool_for_self_learning.py    # Custom tools
├── agent_with_structured_output.py     # Pydantic output
├── agent_with_typed_input_output.py    # Full type safety
├── agent_with_memory.py                # User memory
├── agent_with_state_management.py      # Session state
├── multi_agent_team.py                 # Multi-agent teams
├── sequential_workflow.py              # Step-based agentic workflows
├── config.yaml                         # Agent OS quick prompts
├── run.py                              # Agent OS entrypoint
├── requirements.txt
└── README.md
```

## Swap Models Anytime

Agno is model-agnostic. Same code, different provider:

```python
# Gemini (default in these examples)
from agno.models.google import Gemini
model = Gemini(id="gemini-3-flash-preview")

# OpenAI
from agno.models.openai import OpenAIChat
model = OpenAIChat(id="gpt-4o")

# Anthropic
from agno.models.anthropic import Claude
model = Claude(id="claude-sonnet-4-5")
```

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Agent OS Overview](https://docs.agno.com/agent-os/overview)

---

Built with 💜 by the Agno team
