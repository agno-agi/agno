# Get Started with Agents, The Easy Way

This guide walks through the basics of building Agents with Agno. Follow along to learn how to build agents with memory, knowledge, state, guardrails, and human in the loop. We'll also build multi-agent teams and step-based agentic workflows.

Each example can be run independently and contains detailed comments to help you understand what's happening under the hood. We'll use **Gemini 3 Flash** — fast, affordable, and excellent at tool calling but you can swap in any model with a one line change.

## Files

| # | File | What You'll Learn | Key Features |
|:--|:---------|:------------------|:-------------|
| 01 | `agent_with_tools.py` | Give an agent tools to fetch real-time data | Tool Calling, Data Fetching |
| 02 | `agent_with_structured_output.py` | Return typed Pydantic objects | Structured Output, Type Safety |
| 03 | `agent_with_typed_input_output.py` | Full type safety on input and output | Input Schema, Output Schema |
| 04 | `agent_with_storage.py` | Persist conversations across runs | Persistent Storage, Session Management |
| 05 | `agent_with_memory.py` | Remember user preferences across sessions | Memory Manager, Personalization |
| 06 | `agent_with_state_management.py` | Track, modify, and persist structured state | Session State, State Management |
| 07 | `agent_search_over_knowledge.py` | Load documents into a knowledge base and search with hybrid search | Chunking, Embedding, Hybrid Search, Agentic Retrieval |
| 08 | `custom_tool_for_self_learning.py` | How to write your own tools and add self-learning capabilities | Custom Tools, Self-Learning |
| 09 | `agent_with_guardrails.py` | Add input validation and safety checks | Guardrails, PII Detection, Prompt Injection |
| 10 | `human_in_the_loop.py` | Require user confirmation before executing tools | Human in the Loop, Tool Confirmation |
| 11 | `multi_agent_team.py` | Coordinate multiple agents by organizing them into a team | Multi-Agent Team, Dynamic Collaboration |
| 12 | `sequential_workflow.py` | Sequentially execute agents/teams/functions | Agentic Workflow, Pipelines |

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
| **Guardrails** | Validate and filter input | Block PII, prevent prompt injection |
| **Human in the Loop** | Require confirmation for actions | Sensitive operations, safety-critical tools |

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
uv venv .quickstart --python 3.12
source .quickstart/bin/activate
```

### 3. Install dependencies
```bash
uv pip install -r cookbook/00_quickstart/requirements.txt
```

### 4. Set your API key
```bash
export GOOGLE_API_KEY=your-google-api-key
```

### 5. Run any cookbook
```bash
python cookbook/00_quickstart/agent_with_tools.py
```

**That's it.** No Docker, no Postgres — just Python and an API key.

## Run via Agent OS

Agent OS provides a web interface for interacting with your agents. Start the server:

```bash
python cookbook/00_quickstart/run.py
```

Then visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an endpoint.

Here's how it looks in action — chat with your agents, explore sessions, monitor traces, manage knowledge and memories, all through a beautiful visual UI.

https://github.com/user-attachments/assets/aae0086b-86f6-4939-a0ce-e1ec9b87ba1f

> [!TIP]
> To run the agent-with-knowledge, remember to load the knowledge base first using:
> ```bash
> python cookbook/00_quickstart/agent_search_over_knowledge.py
> ```

## Swap Models Anytime

Agno is model-agnostic. Same code, different provider:

```python
# Gemini (default in these examples)
from agno.models.google import Gemini
model = Gemini(id="gemini-3-flash-preview")

# OpenAI
from agno.models.openai import OpenAIResponses
model = OpenAIResponses(id="gpt-5.2")

# Anthropic
from agno.models.anthropic import Claude
model = Claude(id="claude-sonnet-4-5")
```

## Run Cookbooks Individually

```bash
# 01 - Tools: Fetch real market data
python cookbook/00_quickstart/agent_with_tools.py

# 02 - Structured Output: Get typed responses
python cookbook/00_quickstart/agent_with_structured_output.py

# 03 - Typed I/O: Full type safety
python cookbook/00_quickstart/agent_with_typed_input_output.py

# 04 - Storage: Remember conversations
python cookbook/00_quickstart/agent_with_storage.py

# 05 - Memory: Remember user preferences
python cookbook/00_quickstart/agent_with_memory.py

# 06 - State: Manage watchlists
python cookbook/00_quickstart/agent_with_state_management.py

# 07 - Knowledge: Search your documents
python cookbook/00_quickstart/agent_search_over_knowledge.py

# 08 - Custom Tools: Write your own
python cookbook/00_quickstart/custom_tool_for_self_learning.py

# 09 - Guardrails: Input validation and safety
python cookbook/00_quickstart/agent_with_guardrails.py

# 10 - Human in the Loop: Confirm before executing
python cookbook/00_quickstart/human_in_the_loop.py

# 11 - Teams: Bull vs Bear analysis
python cookbook/00_quickstart/multi_agent_team.py

# 12 - Workflows: Research pipeline
python cookbook/00_quickstart/sequential_workflow.py
```

## Async Patterns

All examples in this Quick Start use synchronous code for simplicity. For async/await patterns (recommended for production), see `cookbook/02_agents/` which includes async variants of most features.

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Agent OS Overview](https://docs.agno.com/agent-os/introduction)
