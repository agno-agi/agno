# Linear Project Manager

A project management agent that integrates with Linear to create issues, update statuses, query project state, and generate progress reports using natural language.

## Quick Start

### 1. Prerequisites

```bash
# Set Linear API key
export LINEAR_API_KEY=your-linear-api-key

# Set OpenAI API key
export OPENAI_API_KEY=your-openai-api-key
```

### 2. Get Linear API Key

1. Go to [Linear Settings](https://linear.app/settings/api)
2. Click "Create new API key"
3. Give it a name (e.g., "Agno Agent")
4. Copy the key and set as `LINEAR_API_KEY`

### 3. Run Examples

```bash
# Create issues
.venvs/demo/bin/python cookbook/01_showcase/01_agents/linear_agent/examples/create_issue.py

# Query issues
.venvs/demo/bin/python cookbook/01_showcase/01_agents/linear_agent/examples/query_issues.py

# Generate progress reports
.venvs/demo/bin/python cookbook/01_showcase/01_agents/linear_agent/examples/progress_report.py
```

## Key Concepts

### Natural Language to Issues

The agent converts natural language into structured issues:

| Input | Extracted |
|-------|-----------|
| "Fix the login bug" | Title: "Fix the login bug" |
| "This is urgent" | Priority: 1 (Urgent) |
| "Assign to John" | Assignee: John's user ID |
| "For the engineering team" | Team: Engineering team ID |

### Priority Mapping

| Keywords | Priority |
|----------|----------|
| Critical, urgent, ASAP, blocking | 1 (Urgent) |
| High priority, important, soon | 2 (High) |
| Normal, standard | 3 (Medium) |
| Low priority, nice to have | 4 (Low) |

### Available Operations

| Tool | Description |
|------|-------------|
| `get_user_details` | Get current user info |
| `get_teams_details` | List available teams |
| `create_issue` | Create new issue |
| `update_issue` | Update issue title |
| `get_issue_details` | Get issue by ID |
| `get_user_assigned_issues` | Issues assigned to user |
| `get_high_priority_issues` | P1/P2 issues |
| `get_workflow_issues` | Issues by state |

## Architecture

```
User Command (Natural Language)
    |
    v
[Linear Agent (GPT-5.2)]
    |
    +---> LinearTools
    |         |
    |         +---> get_teams_details
    |         +---> create_issue
    |         +---> get_user_assigned_issues
    |         +---> get_high_priority_issues
    |         +---> update_issue
    |
    +---> ReasoningTools ---> think/analyze
    |
    +---> Agentic Memory (team prefs)
    |
    v
Issue Created / Query Results / Report
```

## Usage Examples

### Create an Issue

```python
from agent import linear_agent

linear_agent.print_response(
    "Create a bug: Login button not working. High priority.",
    stream=True
)
```

### Query Issues

```python
linear_agent.print_response(
    "What are my assigned issues?",
    stream=True
)

linear_agent.print_response(
    "Show me all high priority issues",
    stream=True
)
```

### Generate Report

```python
linear_agent.print_response(
    "Generate a progress report for standup",
    stream=True
)
```

## Issue Creation Best Practices

The agent follows these conventions:

### Titles
- Start with action verb: Fix, Add, Update, Remove, Implement
- Be specific: "Fix login button" not "Login broken"
- Include area: "[Auth] Fix password reset"

### Descriptions
For bugs:
- Steps to reproduce
- Expected vs actual behavior
- Environment info

For features:
- User story format
- Acceptance criteria
- Design links if available

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model
- `requests` - Linear API calls

## API Credentials

To use this agent, you need:

1. **Linear API key** from Linear Settings
2. **OpenAI API key** for GPT-5.2

See Prerequisites section for setup instructions.
