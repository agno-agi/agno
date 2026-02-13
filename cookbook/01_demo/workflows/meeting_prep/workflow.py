"""
Meeting Prep Workflow
======================

Triggered before a specific meeting. Does deep preparation by researching
attendees, pulling relevant docs, gathering context, and producing talking points.

Steps:
1. Parse meeting details
2. Parallel: Research attendees + Pull internal context + Gather external context
3. Synthesize into a meeting prep brief

Test:
    python -m workflows.meeting_prep.workflow
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from agno.tools.parallel import ParallelTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel

# ---------------------------------------------------------------------------
# Mock Tools
# ---------------------------------------------------------------------------


@tool(
    description="Look up meeting details from the calendar. Returns mock data for demo purposes."
)
def get_meeting_details(meeting_topic: str) -> str:
    """Returns mock meeting details."""
    # Provide a realistic meeting scenario
    return """
Meeting Details:
  Title: Product Strategy Review
  Date: Thursday, February 6, 2025, 10:00 - 11:00 AM
  Location: Conference Room A
  Organizer: Lisa Zhang (VP Product)

  Attendees:
  - James Wilson (CEO) - james@company.com
  - Lisa Zhang (VP Product) - lisa@company.com
  - You (VP Engineering)

  Agenda:
  1. Q4 retrospective (10 min)
  2. Q1 roadmap review (20 min)
  3. Resource allocation & engineering capacity (15 min)
  4. Key decisions needed (15 min)

  Previous Meeting Notes (Jan 15):
  - Agreed to focus Q1 on platform reliability
  - James wanted to explore AI features for Q2
  - Lisa proposed new enterprise tier
  - Action item: You to provide engineering capacity estimates
  - Action item: Lisa to finalize customer interview results

  Related Documents:
  - Q4 Product Metrics Dashboard
  - Q1 Roadmap Draft v2
  - Engineering Capacity Planning Sheet
  - Customer Interview Summary (Lisa)
"""


@tool(
    description="Get internal documents related to a topic. Returns mock data for demo purposes."
)
def get_internal_docs(topic: str) -> str:
    """Returns mock internal documents."""
    return f"""
Related Internal Documents for: {topic}

1. Q4 Product Metrics Dashboard
   - MAU: 45,000 (up 18% QoQ)
   - Revenue: $2.3M (up 23% YoY)
   - Churn: 4.2% (down from 5.1%)
   - NPS: 62 (up from 54)
   - Key insight: Enterprise customers drive 70% of revenue

2. Q1 Roadmap Draft v2 (Lisa Zhang, Jan 28)
   - Theme: "Reliable Foundation"
   - Priority 1: Platform stability (reduce P1 incidents by 50%)
   - Priority 2: Enterprise features (SSO, audit logs, compliance)
   - Priority 3: AI-powered insights (beta)
   - Engineering ask: 3 additional backend engineers

3. Engineering Capacity Planning
   - Current team: 12 engineers (4 backend, 3 frontend, 2 infra, 2 ML, 1 mobile)
   - Q1 committed: 70% on reliability, 20% on enterprise, 10% on AI
   - Risk: ML team stretched thin if AI features accelerated
   - Hiring pipeline: 2 offers out (1 backend, 1 infra)

4. Customer Interview Summary (Lisa Zhang, Jan 30)
   - Interviewed 15 enterprise customers
   - Top requests: SSO (12/15), better API docs (10/15), audit logs (9/15)
   - Surprise finding: 8/15 want AI-powered anomaly detection
   - Quote: "We'd pay 2x for enterprise tier with SSO and compliance"
"""


# ---------------------------------------------------------------------------
# Workflow Agents
# ---------------------------------------------------------------------------
meeting_parser = Agent(
    name="Meeting Parser",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_meeting_details],
    instructions=[
        "You parse meeting details and identify what preparation is needed.",
        "Extract: attendees, agenda items, previous action items, open questions.",
        "Output a structured summary of what needs to be researched and prepared.",
    ],
)

attendee_researcher = Agent(
    name="Attendee Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ParallelTools(enable_extract=False)],
    instructions=[
        "You research meeting attendees to provide context for the meeting.",
        "For each attendee, find: recent public activity, company news, relevant background.",
        "Focus on information that's relevant to the meeting topic.",
        "For internal colleagues, note their role and recent contributions.",
    ],
)

context_gatherer = Agent(
    name="Internal Context Gatherer",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_internal_docs],
    instructions=[
        "You gather internal documents and data relevant to the meeting.",
        "Pull metrics, previous decisions, action items, and relevant docs.",
        "Summarize each document's key points relevant to the meeting agenda.",
    ],
)

external_researcher = Agent(
    name="External Context Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ParallelTools(enable_extract=False)],
    instructions=[
        "You research external context relevant to the meeting topics.",
        "Look for: market trends, competitor moves, industry benchmarks.",
        "Focus on information that could inform decisions in the meeting.",
        "Keep findings brief and actionable.",
    ],
)

prep_synthesizer = Agent(
    name="Prep Synthesizer",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You compile all research into a meeting prep brief.",
        "",
        "Structure the brief as:",
        "## Meeting Overview",
        "- Who, what, when, where",
        "",
        "## Attendee Context",
        "- Brief on each attendee and their likely priorities",
        "",
        "## Key Data Points",
        "- Metrics and facts you should have at your fingertips",
        "",
        "## Previous Decisions & Action Items",
        "- What was decided last time and status of action items",
        "",
        "## Recommended Talking Points",
        "- 5-7 specific points to raise, with supporting data",
        "",
        "## Potential Questions to Expect",
        "- Questions others might ask you, with suggested responses",
        "",
        "## Decision Points",
        "- Decisions that need to be made in this meeting",
        "",
        "Keep it actionable. This is a cheat sheet for walking into the meeting prepared.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
meeting_prep_workflow = Workflow(
    id="meeting-prep",
    name="Meeting Prep",
    steps=[
        Step(name="Parse Meeting", agent=meeting_parser),
        Parallel(
            Step(name="Research Attendees", agent=attendee_researcher),
            Step(name="Gather Internal Context", agent=context_gatherer),
            Step(name="Research External Context", agent=external_researcher),
            name="Deep Research",
        ),
        Step(name="Synthesize Prep Brief", agent=prep_synthesizer),
    ],
)

if __name__ == "__main__":
    test_cases = [
        "Prepare me for my 10 AM Product Strategy Review meeting",
        "Prepare me for the Q1 roadmap review with our CEO and VP Product.",
    ]
    for idx, prompt in enumerate(test_cases, start=1):
        print(f"\n--- Meeting prep workflow test case {idx}/{len(test_cases)} ---")
        print(f"Prompt: {prompt}")
        meeting_prep_workflow.print_response(prompt, stream=True)
