# Agentic Workflows

This feature allows you to add a `WorkflowAgent` to your workflow that intelligently decides whether to:
1. **Answer directly** from workflow session history
2. **Run the workflow** by calling a tool when new processing is needed

## Overview

The `WorkflowAgent` is a restricted version of the `Agent` class specifically designed for workflow orchestration. It uses a tool-based approach to decide when to execute workflows, providing:
- **Better determinism** - Tool calls are explicit and trackable
- **Improved reliability** - Clear decision boundaries between answering and executing
- **Session awareness** - Automatically accesses workflow history for context

## Architecture

```
User Input
    ↓
WorkflowAgent (with workflow execution tool)
    ↓
Decision Point:
    ├─→ Answer from history (no workflow execution)
    └─→ Call run_workflow tool (executes workflow)
         ↓
    Workflow Steps Execute
         ↓
    Results stored in session
         ↓
    Response returned to user
```

## Key Components

### 1. WorkflowAgent Class
A restricted Agent with limited configuration:
- **Allowed**: `model`, `name`, `description`, `instructions`, `debug_mode`, `monitoring`, `add_history_to_context`, `num_history_responses`
- **Not Allowed**: Custom `tools`, `knowledge`, `storage`
- Tools are automatically set by the workflow

### 2. Workflow History Context
Automatically built from previous runs in the session:
```xml
<workflow_history_context>
[run-1]
input: Tell me a story about a husky named Max
response: Once upon a time, there was a...

[run-2]
input: Now tell me about a cat named Luna
response: Luna was a curious cat who...
</workflow_history_context>
```

### 3. Workflow Execution Tool
Automatically created and provided to the agent:
- **Name**: `run_workflow`
- **Purpose**: Execute the complete workflow
- **Returns**: Workflow execution result
- **Effect**: Creates a normal workflow run in the session

## Usage Example

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.agent import WorkflowAgent
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# Define your workflow steps
story_writer = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a 100 word story based on a given topic",
)

story_formatter = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Break down a story into prologue, body, and epilogue",
)

def add_references(step_input: StepInput):
    """Add references to the story"""
    previous_output = step_input.previous_step_content
    if isinstance(previous_output, str):
        return previous_output + "\n\nReferences: https://www.agno.com"

# Create WorkflowAgent
workflow_agent = WorkflowAgent(
    model=OpenAIChat(id="gpt-4o-mini"),
)

# Create Workflow with WorkflowAgent
workflow = Workflow(
    name="Story Generation Workflow",
    description="Generates stories, formats them, and adds references",
    agent=workflow_agent,
    steps=[story_writer, story_formatter, add_references],
    session_id="my_session",
    db=PostgresDb("postgresql://..."),
)

# First call - will run the workflow (new topic)
response1 = workflow.run("Tell me a story about a husky named Max")

# Second call - will answer from history (related to previous run)
response2 = workflow.run("What was Max like?")

# Third call - will run workflow again (new topic)
response3 = workflow.run("Now tell me about a cat named Luna")

# Fourth call - will answer from history (can compare both)
response4 = workflow.run("Compare Max and Luna")
```

## How It Works

### 1. Initialization
When `workflow.run()` is called with an agent configured:
1. Workflow reads/creates session from database
2. Builds history context from previous runs
3. Creates the `run_workflow` tool dynamically
4. Sets up `WorkflowAgent` with tool and context

### 2. Agent Decision
The `WorkflowAgent`:
1. Receives user input
2. Sees workflow history in context
3. Decides to either:
   - Answer directly (using history)
   - Call `run_workflow` tool (to process new query)

### 4. Storage
- **Workflow run**: Stored in `session.runs[]`

## Implementation Details

### WorkflowAgent Restrictions
```python
# ✅ Allowed
workflow_agent = WorkflowAgent(
    model=OpenAIChat(id="gpt-4o"),
    num_history_runs=3
)

# ❌ Not Allowed
workflow_agent = WorkflowAgent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[...],        # Error: tools set by workflow
    knowledge=...,      # Error: not supported
    db=...,             # Error: not supported (uses the workflow db)
    reasoning=...,      # Error: not supported
)
```