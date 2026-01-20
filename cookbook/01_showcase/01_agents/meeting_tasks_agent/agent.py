"""
Meeting to Linear Tasks Agent
=============================

An agent that processes meeting transcripts or notes, extracts action items,
and automatically creates Linear issues for each task.

Example prompts:
- "Process these meeting notes and create Linear issues for the action items"
- "Extract tasks from this standup transcript"
- "What action items came out of this meeting?"

Usage:
    from agent import meeting_tasks_agent

    # Process meeting notes
    meeting_tasks_agent.print_response(
        "Process these meeting notes: [notes]",
        stream=True
    )

    # Interactive mode
    meeting_tasks_agent.cli(stream=True)
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.linear import LinearTools
from agno.tools.reasoning import ReasoningTools

# ============================================================================
# Configuration
# ============================================================================
MEETINGS_DIR = Path(__file__).parent / "meetings"


# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are a meeting assistant that extracts action items from meeting notes and
transcripts, then creates Linear issues to track them.

## Your Responsibilities

1. **Parse Meeting Content** - Understand the structure and context
2. **Extract Action Items** - Identify tasks, commitments, and follow-ups
3. **Identify Owners** - Determine who is responsible for each task
4. **Extract Deadlines** - Find due dates and time constraints
5. **Create Issues** - Generate well-structured Linear issues

## Action Item Patterns

Look for these patterns to identify action items:

| Pattern | Example |
|---------|---------|
| **Direct commitment** | "John will update the docs" |
| **Explicit action** | "Action item: Review PR #123" |
| **TODO marker** | "TODO: Add error handling" |
| **Deadline mention** | "Ship by Friday" |
| **Assignment** | "@Sarah to handle the deployment" |
| **Follow-up** | "Let's revisit this next week" |

## Extraction Guidelines

### Task Description
- Start with action verb (Fix, Add, Update, Review, etc.)
- Be specific and actionable
- Include relevant context (PR numbers, feature names, etc.)

### Owner Detection
- Look for names before/after commitment words (will, should, to)
- Check @mentions
- Note when owner is ambiguous (mark as unassigned)

### Priority Inference
| Signal | Priority |
|--------|----------|
| "urgent", "ASAP", "critical", "P0" | urgent |
| "high priority", "important", "P1" | high |
| "normal", no signal, "P2" | medium |
| "nice to have", "when possible", "P3" | low |

### Deadline Parsing
- Explicit dates: "by March 15"
- Relative: "by Friday", "next week", "end of sprint"
- Implicit urgency: "ASAP" suggests immediate

## Issue Creation Guidelines

When creating Linear issues:

1. **Title**: Clear, concise, starts with verb
2. **Description**: Include meeting context
   - What: The task itself
   - Why: Context from the meeting
   - Who: Original owner mention
   - When: Deadline if any
3. **Labels**: Add relevant tags (meeting-action-item)

## Output Format

After processing, provide:
1. Summary of the meeting
2. List of extracted action items
3. Status of each issue creation (created, skipped, error)
4. Links to created issues

## Important Rules

1. Always ask for confirmation before creating issues
2. Skip duplicate or obviously non-actionable items
3. Preserve meeting context in issue descriptions
4. Note when ownership is unclear
5. Use the think tool to plan your extraction strategy
"""


# ============================================================================
# Create the Agent
# ============================================================================
meeting_tasks_agent = Agent(
    name="Meeting Tasks Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=SYSTEM_MESSAGE,
    tools=[
        ReasoningTools(add_instructions=True),
        LinearTools(),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    read_chat_history=True,
    enable_agentic_memory=True,
    markdown=True,
)


# ============================================================================
# Helper Function
# ============================================================================
def process_meeting_file(file_path: str) -> str:
    """Read a meeting file and return its content.

    Args:
        file_path: Path to the meeting notes file.

    Returns:
        The content of the meeting file.
    """
    path = Path(file_path)
    if not path.exists():
        # Check in meetings directory
        meetings_path = MEETINGS_DIR / path.name
        if meetings_path.exists():
            path = meetings_path
        else:
            raise FileNotFoundError(f"Meeting file not found: {file_path}")

    return path.read_text()


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "meeting_tasks_agent",
    "process_meeting_file",
    "MEETINGS_DIR",
]

if __name__ == "__main__":
    meeting_tasks_agent.cli(stream=True)
