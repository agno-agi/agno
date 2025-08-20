# Agno Agents Cookbook - Developer Guide

Welcome to the **Agno Agents Cookbook** - your comprehensive guide to building intelligent AI agents with Agno. This cookbook contains practical examples, patterns, and best practices for creating powerful AI applications using Agno's agent framework.

- [Agno Agents Cookbook - Developer Guide](#agno-agents-cookbook---developer-guide)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
    - [Key Agent Features](#key-agent-features)
  - [Quick Start](#quick-start)
  - [Sections](#sections)
    - [Tool Integration](#-tool-integration)
    - [RAG & Knowledge](#rag--knowledge)
    - [Human-in-the-Loop](#human-in-the-loop)
    - [Multimodal Capabilities](#multimodal-capabilities)
    - [Async & Performance](#async--performance)
    - [State Management](#state-management)
    - [Event Handling & Streaming](#event-handling--streaming)
    - [Advanced Patterns](#-advanced-patterns)
## Overview

Agno agents are intelligent, autonomous AI systems that can reason, use tools, maintain memory, and interact with users in sophisticated ways - far beyond simple chatbots.

### Key Agent Features

| Feature | Description | Use Cases |
|---------|-------------|-----------|
| **Memory** | Persistent conversation history and learning | Customer support, personal assistants |
| **Tools** | External API integration and function calling | Web search, database queries, calculations |
| **State Management** | Session-based context and data persistence | Multi-turn conversations, workflows |
| **Multimodal** | Image, audio, video processing capabilities | Content analysis, media generation |
| **Human-in-the-Loop** | User confirmation and input workflows | Sensitive operations, data validation |
| **Async Support** | High-performance concurrent operations | Batch processing, real-time applications |
| **RAG Integration** | Knowledge retrieval and augmented generation | Document Q&A, knowledge bases |

## Quick Start

**Basic Agent:**
```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful assistant."
)
agent.print_response("Hello! Tell me a joke.")
```

**Agent with Tools:**
```python
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="You are a research assistant."
)
agent.print_response("What are the latest AI developments?")
```

## Sections

### 🔧 Tool Integration

**External APIs, functions, and capabilities**

Agno agents can use tools in the following ways:

**1. Agno ToolKits** - Ready-to-use tool collections in Agno:
```python
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.calculator import Calculator

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), Calculator()],
    instructions="You can search the web and perform calculations."
)
```

**2. Custom Tools** - Build your own functions:
```python
from agno.tools import tool

@tool
def get_weather(location: str) -> str:
    """Get current weather for a location"""
    # Your custom API integration here
    return f"Current weather in {location}: 72°F, sunny"

@tool
def calculate_tip(bill_amount: float, tip_percent: float = 15.0) -> str:
    """Calculate tip amount"""
    tip = bill_amount * (tip_percent / 100)
    return f"Tip: ${tip:.2f}, Total: ${bill_amount + tip:.2f}"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[get_weather, calculate_tip]
)
```

**3. Custom Toolkits** - Make your own custom Toolkit class
```python
from agno.tools import Toolkit

class RestaurantToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="restaurant_tools")
        
    @tool
    def find_restaurants(self, location: str, cuisine: str) -> str:
        """Find restaurants by location and cuisine"""
        return f"Found 5 {cuisine} restaurants in {location}"
        
    @tool  
    def make_reservation(self, restaurant: str, time: str) -> str:
        """Make a restaurant reservation"""
        return f"Reserved table at {restaurant} for {time}"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[RestaurantToolkit()]
)
```

See the [example](../agents/tool_concepts/custom_tools/include_exclude_tools.py) for more clarity.

**See more examples:** 
- [`tool_concepts/custom_tools/`](./tool_concepts/custom_tools/) 
- [`tool_concepts/toolkits/`](./tool_concepts/toolkits/) 

### RAG & Knowledge

**Retrieval-Augmented Generation and knowledge systems**

```python
from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    # Use LanceDB as the vector database and store embeddings in the `recipes` table
    vector_db=LanceDb(
        table_name="recipes",
        uri="tmp/lancedb",
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge.add_content_sync(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    # Enable RAG by adding references from Knowledge to the user prompt.
    add_knowledge_to_context=True,
    # Set as False because Agents default to `search_knowledge=True`
    search_knowledge=False,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
```

**Examples:**
- [`rag/traditional_rag_lancedb.py`](./rag/traditional_rag_lancedb.py) - Vector-based knowledge retrieval
- [`rag/agentic_rag_pgvector.py`](./rag/agentic_rag_pgvector.py) - Agentic RAG with Pgvector
- [`rag/agentic_rag_with_reranking.py`](./rag/agentic_rag_with_reranking.py) - Enhanced retrieval with reranking


### Human-in-the-Loop (HITL)

**User confirmation, input, and interactive flow**

```python
@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email (requires user confirmation)"""
    return f"Email sent to {to}"

# Handle confirmation flow
response = agent.run("Send an email about the meeting")
if response.is_paused:
    for tool in response.tools_requiring_confirmation:
        tool.confirmed = True  # User approved
    response = agent.continue_run(run_response=response)
```

**Examples:**
- [`human_in_the_loop/confirmation_required.py`](./human_in_the_loop/confirmation_required.py) - Tool execution confirmation
- [`human_in_the_loop/user_input_required.py`](./human_in_the_loop/user_input_required.py) - Dynamic user input collection
- [`human_in_the_loop/external_tool_execution.py`](./human_in_the_loop/external_tool_execution.py) - External system integration
- [`human_in_the_loop/agentic_user_input.py`](./human_in_the_loop/agentic_user_input.py) - Smart user input collection

### Multimodal Capabilities

**Image, audio, and video processing**

```python
from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")
agent.print_response(
    "Write a 3 sentence fiction story about the image",
    images=[Image(filepath=image_path)],
)
```

**Examples:**
- [`multimodal/image_to_text.py`](./multimodal/image_to_text.py) - Image analysis and description
- [`multimodal/audio_sentiment_analysis.py`](./multimodal/audio_sentiment_analysis.py) - Audio processing
- [`multimodal/video_caption_agent.py`](./multimodal/video_caption_agent.py) - Video content understanding
- [`multimodal/generate_image_with_intermediate_steps.py`](./multimodal/generate_image_with_intermediate_steps.py) - Image generation

### Async & Performance

**High-performance and concurrent operations**

```python
import asyncio
from agno.agent import Agent

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
)

async def basic():
    response = await agent.arun(input="Tell me a joke.")
    print(response.content)

if __name__ == "__main__":
    asyncio.run(basic())
```

**Examples:**
- [`async/basic.py`](./async/basic.py) - Basic async agent usage
- [`async/gather_agents.py`](./async/gather_agents.py) - Concurrent agent execution
- [`async/streaming.py`](./async/streaming.py) - Real-time streaming responses

### State Management

Agno agents can maintain state in different ways depending on your needs:

**1. Basic Session State** - Store data within a conversation:
```python
def add_item(session_state, item: str) -> str:
    """Add an item to the shopping list."""
    session_state["shopping_list"].append(item)
    return f"The shopping list is now {session_state['shopping_list']}"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    session_state={"shopping_list": []},  # Initialize state
    tools=[add_item],
    instructions="Current state (shopping list) is: {shopping_list}",  # Use state in instructions
    add_state_in_messages=True,  # Include state in context
)

agent.print_response("Add milk, eggs, and bread to the shopping list")
```

**2. State in Instructions** - Use state variables directly in agent instructions:
```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    session_state={"user_name": "John"},
    instructions="Users name is {user_name}",  # State variable in instructions
    add_state_in_messages=True,
)

agent.print_response("What is my name?")
```

**3. Multi-Session State** - Persist state across different sessions:
```python
from agno.db.postgres import PostgresDb

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url="postgresql://...", session_table="sessions"),
    add_state_in_messages=True,
    instructions="Users name is {user_name} and age is {age}",
)

# Set state for user 1
agent.print_response(
    "What is my name?",
    session_id="user_1_session_1",
    session_state={"user_name": "John", "age": 30}
)

# State persists - loads from database
agent.print_response("How old am I?", session_id="user_1_session_1")
```

**4. Session History Management** - Control how much conversation history to keep:
```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=SqliteDb(db_file="tmp/data.db"),
    add_history_to_context=True,
    num_history_runs=3,  # Keep last 3 interactions
    search_session_history=True,  # Search across sessions
    num_history_sessions=2,  # Include last 2 sessions in search
)

# Each session is tracked separately
agent.print_response("What is the capital of France?", session_id="session_1")
agent.print_response("What is the capital of Japan?", session_id="session_2")
agent.print_response("What did I discuss previously?", session_id="session_3")  # Searches history
```

**Key Features:**
- **`session_state`** - Dictionary for storing temporary session data
- **`{variable}`** - Use state variables directly in instructions
- **`add_state_in_messages=True`** - Include state in conversation context

**See more examples:**
- [`state/session_state_basic.py`](./state/session_state_basic.py) - Basic session state usage
- [`state/session_state_in_instructions.py`](./state/session_state_in_instructions.py) - Using state in instructions
- [`state/session_state_in_context.py`](./state/session_state_in_context.py) - Multi-session state management
- [`state/last_n_session_messages.py`](./state/last_n_session_messages.py) - Managing conversation history
- [`state/dynamic_session_state.py`](./state/dynamic_session_state.py) - Advanced state patterns
- [`state/session_state_multiple_users.py`](./state/session_state_multiple_users.py) - Multi-user scenarios


### Event Handling & Streaming

**Capture and visualize agent events during streaming**

Agno agents emit events during streaming that you can capture for monitoring, debugging, or building interactive UIs:

**Basic Event Streaming** - Monitor tool calls and responses:
```python
import asyncio
from agno.agent import RunEvent, Agent
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
)

async def run_with_events(prompt: str):
    async for event in agent.arun(prompt, stream=True, stream_intermediate_steps=True):
        if event.event == RunEvent.run_started:
            print(f"🚀 Agent started")
        
        elif event.event == RunEvent.tool_call_started:
            print(f"🔧 Tool: {event.tool.tool_name}")
            print(f"📝 Args: {event.tool.tool_args}")
        
        elif event.event == RunEvent.tool_call_completed:
            print(f"✅ Result: {event.tool.result}")
        
        elif event.event == RunEvent.run_content:
            print(event.content, end="")  # Stream response content

asyncio.run(run_with_events("What is the price of Apple stock?"))
```

**Reasoning Events** - Capture chain-of-thought reasoning steps:
```python
reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,  # Enable reasoning mode
)

async def capture_reasoning(prompt: str):
    async for event in reasoning_agent.arun(prompt, stream=True, stream_intermediate_steps=True):
        if event.event == RunEvent.reasoning_started:
            print("🧠 Reasoning started...")
        
        elif event.event == RunEvent.reasoning_step:
            print(f"💭 Thinking: {event.reasoning_content}")
        
        elif event.event == RunEvent.reasoning_completed:
            print("✅ Reasoning complete")
        
        elif event.event == RunEvent.run_content:
            print(event.content, end="")

# Complex reasoning task
task = "Analyze the factors that led to the Treaty of Versailles and its impact on WWII"
asyncio.run(capture_reasoning(task))
```

**Available Events:**
- `RunEvent.run_started` - Agent execution begins
- `RunEvent.run_content` - Response content chunks
- `RunEvent.run_intermediate_content` - Intermediate response content
- `RunEvent.run_completed` - Agent execution ends
- `RunEvent.run_error` - Agent execution error
- `RunEvent.run_cancelled` - Agent execution cancelled
- `RunEvent.run_paused` - Agent execution paused
- `RunEvent.run_continued` - Agent execution continued
- `RunEvent.tool_call_started` - Tool execution begins  
- `RunEvent.tool_call_completed` - Tool execution finished
- `RunEvent.reasoning_started` - Reasoning mode begins
- `RunEvent.reasoning_step` - Individual reasoning steps
- `RunEvent.reasoning_completed` - Reasoning finished
- `RunEvent.memory_update_started` - Memory update begins
- `RunEvent.memory_update_completed` - Memory update finished
- `RunEvent.parser_model_response_started` - Parser model response begins
- `RunEvent.parser_model_response_completed` - Parser model response finished
- `RunEvent.output_model_response_started` - Output model response begins
- `RunEvent.output_model_response_completed` - Output model response finished

**See more examples:**
- [`events/basic_agent_events.py`](./events/basic_agent_events.py) - Tool call event handling
- [`events/reasoning_agent_events.py`](./events/reasoning_agent_events.py) - Reasoning event capture

### Advanced Patterns

**Database Integration** - Direct database operations and chat history:
```python
from agno.db.postgres import PostgresDb

# Agent with PostgreSQL storage
db = PostgresDb(db_url="postgresql://...", session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="chat_history",
    add_history_to_context=True,
)

agent.print_response("Tell me about space")
chat_history = agent.get_chat_history()  # Retrieve conversation history
print(chat_history)
```

**Session Management** - Advanced session control and naming:
```python
# Persistent sessions with custom naming
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url="postgresql://...", session_table="sessions"),
    session_id="my_session",
    add_history_to_context=True,
)

# Custom session naming
agent.print_response("Tell me about space")
agent.set_session_name(session_name="Space Facts Discussion")

# Auto-generate session names
agent.set_session_name(autogenerate=True)

# Retrieve session details
session = agent.get_session(session_id=agent.session_id)
print(session.session_data.get("session_name"))
```

**Dependency Injection** - Add external data to agent context:
```python
import json

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat


def get_top_hackernews_stories(num_stories: int = 5) -> str:
    """Fetch and return the top stories from HackerNews.

    Args:
        num_stories: Number of top stories to retrieve (default: 5)
    Returns:
        JSON string containing story details (title, url, score, etc.)
    """
    # Get top stories
    stories = [
        {
            k: v
            for k, v in httpx.get(
                f"https://hacker-news.firebaseio.com/v0/item/{id}.json"
            )
            .json()
            .items()
            if k != "kids"  # Exclude discussion threads
        }
        for id in httpx.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        ).json()[:num_stories]
    ]
    return json.dumps(stories, indent=4)


# Create a Context-Aware Agent that can access real-time HackerNews data
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Each function in the dependencies is resolved when the agent is run,
    # think of it as dependency injection for Agents
    dependencies={"top_hackernews_stories": get_top_hackernews_stories},
    # We can add the entire dependencies dictionary to the user message
    add_dependencies_to_context=True,
    markdown=True,
)

# Example usage
agent.print_response(
    "Summarize the top stories on HackerNews and identify any interesting trends.",
    stream=True,
)

```

## Parser Model & Output Model

Agno supports specialized models for different stages of agent processing, allowing you to optimize performance, cost, and quality for specific tasks.

### Parser Model

The `parser_model` is used specifically for parsing structured outputs when using `response_model`. This allows you to use a faster, cheaper model for the parsing task while using a more powerful model for the main reasoning.

**Benefits:**
- **Cost Optimization** - Use cheaper models (like GPT-4o-mini) for parsing while using premium models for reasoning
- **Performance** - Faster parsing with models optimized for structured data extraction
- **Reliability** - Dedicated parsing models often have better JSON/structured output consistency
- **Resource Allocation** - Separate concerns between reasoning and parsing tasks

**Example:**
```python
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from pydantic import BaseModel

class TravelPlan(BaseModel):
    destination: str
    duration_days: int
    budget_usd: float
    activities: list[str]

agent = Agent(
    model=Claude(id="claude-sonnet-4"),  # Powerful model for reasoning
    parser_model=OpenAIChat(id="gpt-4o"),  # Fast model for parsing
    response_model=TravelPlan,
)
```

### Output Model

The `output_model` is used to generate the final response after all processing is complete. This enables you to use different models for different stages of the agent workflow.

**Benefits:**
- **Quality Control** - Use specialized models for final output generation
- **Style Consistency** - Different models for different response styles (technical vs conversational)
- **Cost Management** - Use expensive models only for final output, cheaper models for intermediate steps
- **Multi-Modal Support** - Use text models for reasoning, multi-modal models for final responses

**Example:**
```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4"),  # Standard model for reasoning and tool use
    output_model=OpenAIChat(id="o3-mini"),  # Specialized model for final response
    tools=[DuckDuckGoTools()],
)

agent.print_response("Latest news from France?", stream=True)
```

**See Examples:**
- [`other/parse_model.py`](./other/parse_model.py) - Parser model for structured outputs
- [`other/output_model.py`](./other/output_model.py) - Output model for final responses


**Examples:**
- **[`db/`](./db/)** - Database integration patterns
  - `chat_history.py` - Retrieving conversation history
  - `session_storage.py` - Persistent session storage
  - `user_memories.py` - User-specific memory storage
- **[`session/`](./session/)** - Advanced session management
  - `01_persistent_session.py` - Basic session persistence
  - `06_rename_session.py` - Custom session naming
  - `07_in_memory_session_caching.py` - Performance optimization
- **[`dependencies/`](./dependencies/)** - Dependency injection patterns
  - `add_dependencies_to_context.py` - Injecting external data into agent context

---