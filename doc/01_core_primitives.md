# Core Primitives: Agent, Team, Workflow

Agno is built on three composable primitives. Every AI system you build uses one or more of these.

| Primitive | Use when… |
|-----------|-----------|
| `Agent` | A single autonomous entity that can use tools, memory, and knowledge |
| `Team` | Multiple agents coordinating on a shared goal |
| `Workflow` | Deterministic, graph-based multi-step execution |

---

## Agent

**Files:** `libs/agno/agno/agent/agent.py` · `libs/agno/agno/agent/_run.py`

An `Agent` is the smallest complete unit: it has a model, optional tools, optional knowledge, optional memory, and it produces a response.

### Minimal agent

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.print_response("What is the capital of France?")
```

### Agent with tools

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("What happened in AI this week?")
```

### Agent with structured output

```python
from pydantic import BaseModel
from agno.agent import Agent
from agno.models.openai import OpenAIChat

class MovieReview(BaseModel):
    title: str
    year: int
    rating: float
    summary: str

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    output_schema=MovieReview,
)
result = agent.run("Review Dune: Part Two")
review: MovieReview = result.content  # typed Pydantic object
print(review.rating)
```

### Agent with persistent session history

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.postgres import PostgresDb

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(table_name="sessions", db_url="postgresql://..."),
    session_id="user-42-chat",
    add_history_to_messages=True,
    num_history_runs=10,
)
agent.print_response("My name is Alice.")
agent.print_response("What is my name?")  # Remembers "Alice"
```

### Streaming

```python
# Sync streaming
for chunk in agent.run("Tell me a story", stream=True):
    print(chunk.content, end="", flush=True)

# Async streaming
async for chunk in await agent.arun("Tell me a story", stream=True):
    print(chunk.content, end="", flush=True)
```

### Key Agent parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | LLM to use (43+ providers) |
| `tools` | `list` | Tool instances/toolkits |
| `knowledge` | `Knowledge` | RAG knowledge base |
| `memory` | `MemoryManager` | Cross-session persistent memory |
| `db` | `Database` | Session/history storage backend |
| `instructions` | `str \| list` | System prompt |
| `output_schema` | `BaseModel` | Typed structured output |
| `reasoning` | `bool` | Enable step-by-step reasoning |
| `guardrails` | `list` | Input/output safety checks |
| `hooks` | `list` | Pre/post execution hooks |
| `session_id` | `str` | Persist sessions across calls |
| `user_id` | `str` | User-scoped isolation |
| `stream` | `bool` | Stream tokens as generated |
| `stream_intermediate_steps` | `bool` | Stream tool call details |
| `show_tool_calls` | `bool` | Print tool calls in output |
| `markdown` | `bool` | Format response as markdown |
| `add_history_to_messages` | `bool` | Inject chat history |
| `num_history_runs` | `int` | How many past runs to include |

---

## Team

**Files:** `libs/agno/agno/team/team.py` · `libs/agno/agno/team/_run.py`

A `Team` coordinates multiple agents. The team has a leader model (the `Team`'s own `model=`) that decides how to route, coordinate, or broadcast work to member agents.

### Team execution modes

| Mode | Behaviour |
|------|-----------|
| `route` | Leader picks the single best member for each message |
| `coordinate` | Leader breaks task into subtasks, assigns to members, synthesises result |
| `broadcast` | All members receive every message and respond independently |
| `tasks` | Leader assigns structured tasks to members and tracks completion |

### Route mode — delegate to the right specialist

```python
from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

web_agent = Agent(
    name="Web Agent",
    role="Search the web for current news and information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
)

finance_agent = Agent(
    name="Finance Agent",
    role="Analyse stock prices, earnings reports, and financial data",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools(stock_price=True, analyst_recommendations=True)],
)

team = Team(
    name="Research Team",
    mode="route",
    model=OpenAIChat(id="gpt-4o"),
    members=[web_agent, finance_agent],
    instructions="Route each question to the most relevant specialist.",
    show_tool_calls=True,
    markdown=True,
)

team.print_response("What is Apple's current stock price and recent news?")
```

### Coordinate mode — leader synthesises member work

```python
from agno.team import Team
from agno.models.openai import OpenAIChat

team = Team(
    name="Writing Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[researcher, writer, editor],  # three specialist agents
    instructions=[
        "Coordinate members to produce polished, well-researched articles.",
        "Researcher gathers facts; Writer drafts; Editor polishes.",
    ],
)
team.print_response("Write a 500-word article on quantum computing breakthroughs in 2025.")
```

### Nested teams

```python
analysis_team = Team(mode="coordinate", members=[data_agent, stats_agent])
writing_team  = Team(mode="coordinate", members=[writer, editor])

master_team = Team(
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[analysis_team, writing_team],
)
```

### Team features

- **Shared session state** — all members read/write a common `session_state` dict
- **Team-level tools** — tools defined on the `Team` are available to all members
- **Team-level knowledge** — shared `Knowledge` base injected into all members
- **Session summaries** — long team sessions are auto-summarised to stay within context
- **Parallel execution** — members can work concurrently
- **Remote teams** — `RemoteTeam` runs team members over a network

---

## Workflow

**Files:** `libs/agno/agno/workflow/workflow.py` · sub-modules: `step.py`, `parallel.py`, `loop.py`, `router.py`, `condition.py`, `cel.py`

A `Workflow` is deterministic graph-based orchestration. Unlike a `Team` (where the LLM decides next steps), a `Workflow` follows the code you write. Use it when you need predictable, auditable, reproducible pipelines.

### Workflow primitives

| Class | Purpose |
|-------|---------|
| `Step` | A single unit of work (agent call, tool call, Python function) |
| `Steps` | Sequential list of steps |
| `Parallel` | Run multiple steps concurrently |
| `Loop` | Iterative execution (for / while) |
| `Router` | Switch/case conditional branching |
| `Condition` | Boolean decision logic |
| `@pause` | Decorator — insert a human approval checkpoint |

### Sequential workflow

```python
from agno.workflow import Workflow
from agno.agent import Agent
from agno.models.openai import OpenAIChat

class BlogPipeline(Workflow):
    researcher = Agent(name="Researcher", tools=[DuckDuckGoTools()])
    writer     = Agent(name="Writer")
    editor     = Agent(name="Editor")

    def run(self, topic: str) -> str:
        research = yield self.researcher.run(f"Research: {topic}")
        draft    = yield self.writer.run(f"Write about {topic}. Facts:\n{research.content}")
        final    = yield self.editor.run(f"Edit this draft:\n{draft.content}")
        return final.content

pipeline = BlogPipeline()
result = pipeline.run("The future of renewable energy")
```

### Parallel execution

```python
from agno.workflow import Workflow, Parallel

class ParallelResearch(Workflow):
    researcher = Agent(name="Researcher", tools=[DuckDuckGoTools()])
    writer     = Agent(name="Writer")

    def run(self, topic: str) -> str:
        # Both queries run at the same time
        results = yield Parallel(
            self.researcher.run(f"Technical aspects of {topic}"),
            self.researcher.run(f"Business implications of {topic}"),
        )
        combined = "\n\n".join(r.content for r in results)
        summary  = yield self.writer.run(f"Summarise:\n{combined}")
        return summary.content
```

### Conditional branching

```python
from agno.workflow import Workflow, Router

class RoutingWorkflow(Workflow):
    tech_agent    = Agent(name="Tech Expert")
    finance_agent = Agent(name="Finance Expert")
    general_agent = Agent(name="General Assistant")

    def run(self, question: str, category: str) -> str:
        response = yield Router(
            condition=category,
            routes={
                "tech":    self.tech_agent.run(question),
                "finance": self.finance_agent.run(question),
            },
            default=self.general_agent.run(question),
        )
        return response.content
```

### Human checkpoint with `@pause`

```python
from agno.workflow import Workflow, pause

class ApprovalWorkflow(Workflow):
    drafter   = Agent(name="Drafter")
    publisher = Agent(name="Publisher")

    def run(self, topic: str) -> str:
        draft = yield self.drafter.run(f"Draft an email about: {topic}")

        @pause
        def human_review(content):
            """Pause here for human approval before sending."""
            return content

        approved_draft = yield human_review(draft.content)
        result = yield self.publisher.run(f"Publish: {approved_draft}")
        return result.content
```

### CEL expressions in conditions

Agno supports **Common Expression Language** for complex conditions in workflow edges:

```python
from agno.workflow import Condition

cond = Condition(
    expression="score >= 8.0 && category in ['tech', 'science']",
    variables={"score": 9.2, "category": "tech"},
)
if cond.evaluate():
    # proceed to publish branch
```

### State persistence

Workflows use the same `db=` backend as agents for state persistence and resume:

```python
workflow = MyWorkflow(
    db=PostgresDb(table_name="workflow_sessions", db_url="..."),
    session_id="pipeline-run-001",
)
```

---

## Choosing Between Primitives

```
Single task, one model → Agent
Multi-domain task, need specialist routing → Team (route mode)
Complex task needing coordination → Team (coordinate mode)
Predictable, repeatable pipeline → Workflow
Workflow with human approval gates → Workflow + @pause
```

All three primitives support:
- Sync and async execution
- Streaming responses
- Tool calling
- Session persistence
- Multi-modal inputs (images, audio, video)
