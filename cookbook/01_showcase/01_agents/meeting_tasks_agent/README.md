# Meeting to Linear Tasks Agent

An agent that processes meeting transcripts or notes, extracts action items, and automatically creates Linear issues to track them.

## Quick Start

### 1. Prerequisites

```bash
# Set Linear API key
export LINEAR_API_KEY=your-linear-api-key

# Set OpenAI API key
export OPENAI_API_KEY=your-openai-api-key
```

### 2. Run Examples

```bash
# Process meeting notes (extraction only)
.venvs/demo/bin/python cookbook/01_showcase/01_agents/meeting_tasks_agent/examples/process_notes.py

# Create Linear issues from transcript
.venvs/demo/bin/python cookbook/01_showcase/01_agents/meeting_tasks_agent/examples/create_issues.py

# Process retrospective actions
.venvs/demo/bin/python cookbook/01_showcase/01_agents/meeting_tasks_agent/examples/retro_actions.py
```

## Key Concepts

### Action Item Patterns

The agent recognizes these patterns:

| Pattern | Example |
|---------|---------|
| **Direct commitment** | "John will update the docs" |
| **Explicit action** | "Action item: Review PR #123" |
| **TODO marker** | "TODO: Add error handling" |
| **Deadline mention** | "Ship by Friday" |
| **Assignment** | "@Sarah to handle deployment" |

### Extraction Process

```
Meeting Content
    |
    v
[Parse & Understand]
    |
    v
[Identify Action Items]
    |
    +---> Pattern matching
    +---> Context analysis
    +---> Owner detection
    |
    v
[Extract Details]
    |
    +---> Task description
    +---> Owner
    +---> Deadline
    +---> Priority
    |
    v
[Create Linear Issues]
```

### Priority Inference

| Signal | Priority |
|--------|----------|
| "urgent", "ASAP", "P0" | Urgent |
| "high priority", "P1" | High |
| "normal", no signal | Medium |
| "nice to have", "P3" | Low |

## Architecture

```
Meeting Content (text/transcript)
    |
    v
[Meeting Tasks Agent (GPT-5.2)]
    |
    +---> Parse meeting content
    |
    +---> Extract action items
    |         |
    |         +---> Task description
    |         +---> Owner
    |         +---> Deadline
    |         +---> Priority
    |
    +---> LinearTools
    |         |
    |         +---> get_teams_details
    |         +---> create_issue
    |
    +---> ReasoningTools ---> think/analyze
    |
    v
Created Issues with URLs
```

## Sample Meeting Files

The `meetings/` directory contains sample content:

| File | Type | Content |
|------|------|---------|
| `standup_notes.md` | Daily standup | Updates, blockers, action items |
| `planning_transcript.txt` | Sprint planning | Feature discussions, assignments |
| `retro_notes.md` | Retrospective | Improvements, process changes |

## Usage Examples

### Extract Action Items (No Issue Creation)

```python
from agent import meeting_tasks_agent

meeting_tasks_agent.print_response(
    """Extract action items from these notes:

    Sarah will review the PR by tomorrow.
    Mike needs to update the docs.
    TODO: Add tests for the new API.
    """,
    stream=True
)
```

### Create Linear Issues

```python
meeting_tasks_agent.print_response(
    """Process this meeting and create Linear issues:

    [Your meeting notes here]

    Create issues for each action item.""",
    stream=True
)
```

### Process a File

```python
from agent import meeting_tasks_agent, process_meeting_file

content = process_meeting_file("meetings/standup_notes.md")
meeting_tasks_agent.print_response(
    f"Extract and create issues from: {content}",
    stream=True
)
```

## Issue Creation Best Practices

The agent follows these conventions:

### Titles
- Start with action verb
- Be specific: "Review auth PR #234" not "Review PR"
- Include identifiers when available

### Descriptions
Include meeting context:
```
**Meeting:** Daily Standup - Jan 15
**Owner:** Sarah
**Original context:** "Sarah will review John's auth PR today"

Review and approve authentication refactor PR #234.
Focus on security implications of the new token handling.
```

### Labels
- `meeting-action-item` - Source tracking
- `blocked` - If item has dependencies
- Process-specific labels as appropriate

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model
- `requests` - Linear API calls

## API Credentials

To use this agent, you need:

1. **Linear API key** from Linear Settings
2. **OpenAI API key** for GPT-5.2

See Prerequisites section for setup instructions.
