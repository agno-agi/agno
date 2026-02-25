"""
Coordinate Mode: Incident Response Orchestration
=================================================

Demonstrates selective member coordination where the team lead picks specific
members, crafts targeted tasks, and synthesizes responses into a unified output.

Inspired by Claude Cowork's cross-application workflows that handle multi-step
tasks end-to-end across different domains.

Key patterns:
- Team lead selectively delegates to relevant members based on context
- Each member contributes their domain expertise
- Lead synthesizes diverse inputs into coherent action plan
- Not all members are used for every request (unlike broadcast)

Run with: .venvs/demo/bin/python cookbook/05_agent_os/team_modes/coordinate_mode.py
Access at: http://localhost:7777
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
db = PostgresDb(
    id="team-modes-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Incident Response Specialists
# ---------------------------------------------------------------------------

infra_engineer = Agent(
    name="Infrastructure Engineer",
    id="infra-engineer",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Investigate infrastructure health, capacity, and resource utilization",
    instructions=[
        "Check CPU, memory, disk, and network metrics.",
        "Identify any recent infrastructure changes or deployments.",
        "Look for cascading failures or resource exhaustion patterns.",
        "Provide specific remediation steps for infrastructure issues.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

database_admin = Agent(
    name="Database Administrator",
    id="database-admin",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Investigate database performance, locks, and query patterns",
    instructions=[
        "Analyze slow query logs and lock contention.",
        "Check replication lag and connection pool exhaustion.",
        "Identify any schema changes or migration issues.",
        "Recommend query optimizations or scaling actions.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

app_engineer = Agent(
    name="Application Engineer",
    id="app-engineer",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Investigate application errors, service health, and code issues",
    instructions=[
        "Analyze error rates, latency percentiles, and exception patterns.",
        "Check for recent code deployments or feature flag changes.",
        "Trace requests through the service mesh to find bottlenecks.",
        "Identify memory leaks, thread pool exhaustion, or circuit breaker trips.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

security_analyst = Agent(
    name="Security Analyst",
    id="security-analyst",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Investigate security implications and potential attack vectors",
    instructions=[
        "Check for unusual traffic patterns or potential DDoS.",
        "Analyze authentication failures and suspicious access patterns.",
        "Look for signs of data exfiltration or unauthorized access.",
        "Recommend immediate containment actions if threat detected.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

customer_success = Agent(
    name="Customer Success Manager",
    id="customer-success",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    role="Assess customer impact and coordinate communication",
    instructions=[
        "Identify affected customers and their SLA commitments.",
        "Draft customer communication for different severity levels.",
        "Coordinate with support team on ticket triage.",
        "Track business metrics impact (revenue, churn risk).",
    ],
    update_memory_on_run=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Incident Response Team (Coordinate Mode)
# ---------------------------------------------------------------------------

incident_team = Team(
    name="Incident Response Team",
    id="incident-response-team",
    description="Cross-functional incident response team with selective member coordination",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[
        infra_engineer,
        database_admin,
        app_engineer,
        security_analyst,
        customer_success,
    ],
    mode=TeamMode.coordinate,
    instructions=[
        "You are an Incident Commander coordinating a production incident response.",
        "",
        "Response Protocol:",
        "1. TRIAGE: Assess the incident severity (P1/P2/P3/P4) based on symptoms",
        "2. SCOPE: Identify which systems and domains are likely affected",
        "3. DELEGATE: Engage ONLY the relevant specialists (not everyone)",
        "4. SYNTHESIZE: Combine findings into a unified incident report",
        "",
        "Severity Classification:",
        "- P1: Complete service outage, all users affected",
        "- P2: Major degradation, >50% users affected",
        "- P3: Minor degradation, <50% users affected",
        "- P4: Isolated issue, workaround available",
        "",
        "Coordination Rules:",
        "- For performance issues: engage infra + database + app engineers",
        "- For security alerts: engage security analyst first, then others",
        "- For customer escalations: engage customer success + app engineer",
        "- Always synthesize into: Root Cause, Impact, Remediation, Prevention",
        "",
        "Do NOT engage all members for every incident. Select based on symptoms.",
    ],
    markdown=True,
    show_members_responses=True,
    add_team_history_to_members=True,
    determine_input_for_members=True,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# AgentOS Setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Incident Response with Coordinate Mode - Selective member delegation and synthesis",
    agents=[infra_engineer, database_admin, app_engineer, security_analyst, customer_success],
    teams=[incident_team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Access the API at: http://localhost:7777
    View configuration at: http://localhost:7777/config

    Example incident to try:
    "INCIDENT: payment-api P95 latency spiked from 200ms to 3500ms, DB connection pool at 98%"
    """
    agent_os.serve(app="coordinate_mode:app", reload=True)
