# Job Application Tracker Workflow

A practical agentic workflow that combines **custom tools**, **Pydantic structured output**, and **SQLite session storage** into one real-world example: tracking your job applications across conversations.

## What this demonstrates

| Concept | Where |
|---|---|
| Custom `@tool` functions | `add_application`, `list_applications`, `update_status`, `get_summary` |
| Pydantic model for typed data | `JobApplication` model with validation |
| Persistent SQLite storage | `SqliteStorage` — agent remembers context across runs |
| Multi-turn conversation | `add_history_to_messages=True` |
| Structured agent instructions | Domain-specific behaviour prompts |

## Setup

```bash
pip install agno google-generativeai
export GOOGLE_API_KEY=your_api_key
```

> **Model-agnostic:** swap Gemini for OpenAI or Anthropic with one line:
> ```python
> from agno.models.openai import OpenAIChat
> model = OpenAIChat(id="gpt-4o-mini")
> ```

## Run

```bash
python cookbook/04_workflows/job_application_tracker/job_application_tracker.py
```

## Example prompts

```
# Track a new application
Track this job: Backend Engineer at Zepto, https://zepto.com/careers/123, found on LinkedIn

# List all applications
Show me all my applications

# Filter by status
Show me jobs where I have an interview scheduled

# Update status
Update application #1 to Interview Scheduled

# Get a summary
How many jobs have I applied to?
```

## Example session

```
You: Track this job: Python Developer at Razorpay, https://razorpay.com/jobs/42, applied via Instahyre

Agent: ✅ Saved! Application #1 — Python Developer at Razorpay (Applied)
       Added on 2026-06-28. Want to add any notes or track another application?

You: Show me all my applications

Agent: | # | Role              | Company  | Status  | Applied    | Source     |
       |---|-------------------|----------|---------|------------|------------|
       | 1 | Python Developer  | Razorpay | Applied | 2026-06-28 | Instahyre  |

You: summary

Agent: 📊 Job Application Summary (1 total):
         • Applied: 1
```

## File structure

```
cookbook/04_workflows/job_application_tracker/
├── job_application_tracker.py   # Main workflow
├── requirements.txt
└── README.md
```

## How it works

1. The agent receives a natural language prompt
2. It selects the right tool (`add_application`, `list_applications`, etc.)
3. Pydantic validates the structured data before it hits the DB
4. SQLite persists both the applications and the conversation history
5. On the next run, the agent picks up exactly where it left off
