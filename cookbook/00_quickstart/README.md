# Build an Agent That Can Act, Remember, and Improve

Start with one useful Gemini-powered agent. Add typed outputs, sessions,
memory, state, knowledge, learning, safety, teams, and workflows. Then launch
the whole system in AgentOS.

**One API key. No Docker. Every example runs independently.**

This is a capability ladder, not a collection of unrelated demos. Each file
upgrades the same market-research partner and ends with something you can
inspect: a tool call, typed object, stored session, recalled memory, state
change, knowledge result, learning, blocked request, approval, team response,
or workflow output.

## Start Here

From the repository root:

```bash
uv venv .venvs/quickstart --python 3.12
source .venvs/quickstart/bin/activate
uv pip install -r cookbook/00_quickstart/requirements.txt
export GOOGLE_API_KEY=your-google-api-key
python cookbook/00_quickstart/agent_with_tools.py
```

The first example is the complete minimum:

```python
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Gemini(id="gemini-3.6-flash"),
    tools=[YFinanceTools()],
)

agent.print_response("What's AAPL's current price?", stream=True)
```

Gemini 3.6 Flash is the stable default for this quickstart. It supports the
tool calling, structured output, and multi-step agent work used throughout
the folder. See the [official model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash).

## The Capability Ladder

Follow the files in order for the full journey, or jump directly to the
capability you need. Every example is standalone.

### 1. Core — Make the Agent Useful

| # | Cookbook | What You Add | Proof |
|---:|:---------|:-------------|:------|
| 01 | [`agent_with_tools.py`](agent_with_tools.py) | Live tools | The agent chooses and calls Yahoo Finance tools |
| 02 | [`agent_with_structured_output.py`](agent_with_structured_output.py) | Typed output | The run returns a validated Pydantic object |
| 03 | [`agent_with_typed_input_output.py`](agent_with_typed_input_output.py) | Input and output contracts | Both sides of the agent boundary are validated |

### 2. Context — Make It Durable

| # | Cookbook | What You Add | Proof |
|---:|:---------|:-------------|:------|
| 04 | [`agent_with_storage.py`](agent_with_storage.py) | Conversation storage | A fixed session continues across runs |
| 05 | [`agent_with_memory.py`](agent_with_memory.py) | User memory | Preferences survive across sessions |
| 06 | [`agent_with_state_management.py`](agent_with_state_management.py) | Structured state | The agent updates and restores a watchlist |
| 07 | [`agent_search_over_knowledge.py`](agent_search_over_knowledge.py) | Searchable knowledge | The answer is grounded in a versioned local Agno overview |
| 08 | [`agent_with_learning.py`](agent_with_learning.py) | Shared learned knowledge | One user teaches a rule another user can reuse |

### 3. Trust — Keep the Human in Control

| # | Cookbook | What You Add | Proof |
|---:|:---------|:-------------|:------|
| 09 | [`agent_with_guardrails.py`](agent_with_guardrails.py) | Built-in and custom guardrails | PII, injection, and spam inputs end with `RunStatus.error` |
| 10 | [`human_in_the_loop.py`](human_in_the_loop.py) | Approval gates | The run pauses before a simulated publish action |

### 4. Scale — Move Beyond One Agent

| # | Cookbook | What You Add | Proof |
|---:|:---------|:-------------|:------|
| 11 | [`multi_agent_team.py`](multi_agent_team.py) | Dynamic collaboration | Bull and bear researchers are coordinated by a leader |
| 12 | [`sequential_workflow.py`](sequential_workflow.py) | Explicit orchestration | Gather, analyze, and write steps run in order |

### 5. Ship — Run the Complete System

[`run.py`](run.py) registers every agent, the team, and the workflow in one
AgentOS runtime. [`config.yaml`](config.yaml) adds ready-to-run prompts for the
AgentOS chat interface.

## The Mental Model

These concepts sound similar until you ask what each one owns:

| Concept | What It Owns | Use It For |
|:--------|:-------------|:-----------|
| **Tools** | Actions the model can choose | APIs, search, code, database operations |
| **Structured output** | The response contract | Pipelines, APIs, UIs, reliable parsing |
| **Storage** | The conversation record | Continue the same thread later |
| **Memory** | Durable facts about a user | Preferences and personalization |
| **State** | Mutable structured data | Lists, counters, carts, task progress |
| **Knowledge** | Information the agent can search | Docs, policies, product data, RAG |
| **Learning** | Reusable lessons from prior work | Shared heuristics and better future behavior |
| **Guardrails** | Input and output boundaries | Privacy, policy, and validation |
| **Human in the loop** | Approval for a pending action | Publishing, writes, payments, deployments |
| **Team** | Dynamic delegation between agents | Multiple perspectives or specialists |
| **Workflow** | Explicit execution order | Repeatable multi-step processes |

Start with one agent. Add a team only when independent specialists improve the
answer. Add a workflow when the order of operations must be predictable.

## Run the Complete System in AgentOS

Load the local Agno overview used by the knowledge agent once:

```bash
python cookbook/00_quickstart/agent_search_over_knowledge.py
```

Start AgentOS:

```bash
python cookbook/00_quickstart/run.py
```

Open [os.agno.com](https://os.agno.com), add
`http://localhost:7777` as an endpoint, and choose any quickstart agent, team,
or workflow. You can chat, inspect sessions, view traces, and explore memory
and knowledge from the same interface.

https://github.com/user-attachments/assets/aae0086b-86f6-4939-a0ce-e1ec9b87ba1f

## Why Market Research?

The scenario makes agent behavior visible: facts change, tools matter,
comparisons benefit from structure, and opposing researchers have a real
reason to collaborate. Yahoo Finance also works without a second API key.

The examples teach agent architecture, not investment advice. Replace the
tools and instructions with your own domain while keeping the same patterns.

## Swap Models

Each file declares its own model so it stays copy-pasteable:

```python
from agno.models.google import Gemini

model = Gemini(id="gemini-3.6-flash")
```

Replace that model in the example you are using. The memory example also has a
dedicated memory model, while the knowledge and learning examples use
`GeminiEmbedder`; those components can be configured independently.

Browse [`cookbook/90_models/`](../90_models) for other providers and
provider-specific capabilities.

## Local State

Persistent examples write only to `tmp/quickstart/`, with a separate SQLite
database or Chroma collection per capability. This keeps examples independent
and prevents one run from contaminating another. Delete that directory when
you want a completely fresh start.

## Verify the Folder

Check the cookbook structure and compile every file:

```bash
python3 cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/00_quickstart
python -m compileall -q cookbook/00_quickstart
```

Use [`TEST_PROMPT.md`](TEST_PROMPT.md) for the live behavioral test plan and
[`TEST_LOG.md`](TEST_LOG.md) for the latest verified results.

## Go Deeper

- [Agents](../02_agents) — tools, multimodal input, reasoning, hooks, and advanced patterns
- [Teams](../03_teams) — delegation, collaboration, and team coordination
- [Workflows](../04_workflows) — conditions, loops, routers, and parallel steps
- [AgentOS](../05_agent_os) — production runtime, interfaces, and deployment
- [Knowledge](../07_knowledge) — readers, chunking, embedders, and vector databases
- [Learning](../08_learning) — profiles, entity memory, learned knowledge, and decision logs
- [Agno documentation](https://docs.agno.com)
