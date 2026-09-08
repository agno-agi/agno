"""
Claim Review + Draft Response AgentOS
Team and OS implementation for multi-agent claim processing.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path
from agno.os import AgentOS
from agno.team import Team
from agno.models.google import Gemini
from agno.media import File
from agent import (
    claim_ingestor_agent,
    rule_checker_agent,
    draft_response_agent,
    memory_db,
)

# Create storage directory if it doesn't exist
Path("storage").mkdir(exist_ok=True)

# ============================================================================
# Claim Review Team
# ============================================================================
claim_review_team = Team(
    name="Claim Review Team",
    members=[claim_ingestor_agent, rule_checker_agent, draft_response_agent],
    model=Gemini(id="gemini-2.0-flash"),
    db=memory_db,
    markdown=True,  # Enable markdown rendering in UI
    show_members_responses=False,  # Hide step outputs in UI - only show final team response
    instructions=[
        "Coordinate with team members to process insurance claims end-to-end.",
        "The user will provide both claim documents and policy documents as input.",
        "",
        "Delegate tasks based on the claim processing workflow:",
        "1. First, have the Claim Ingestor extract relevant fields from the claim documents provided by the user.",
        "   - Pass the claim documents (invoices, forms, PDFs, etc.) directly to the Claim Ingestor agent.",
        "",
        "2. Then, have the Rule Checker verify the claim against policy rules and thresholds.",
        "   - Pass the policy document provided by the user directly to the Rule Checker agent.",
        "   - The policy document can be any type (PDF, text, etc.) - Gemini supports all file types natively.",
        "   - The Rule Checker MUST process the actual policy document - it cannot make up policy data.",
        "",
        "3. Finally, have the Draft Response Agent write the approval or denial response.",
        "   - Pass both the Claim JSON (from Claim Ingestor) and Policy JSON (from Rule Checker) to the Draft Response Agent.",
        "",
        "Ensure smooth handoff between team members and maintain context throughout the process.",
        "",
        "IMPORTANT: When the Draft Response Agent completes its work, you MUST include the complete draft response in your final output to the user.",
        "Do not just summarize that the work is done - always include the actual draft response content that the Draft Response Agent created.",
        "",
        "CRITICAL FORMATTING:",
        "- The Draft Response Agent's output is already properly formatted markdown.",
        "- You MUST output the Draft Response Agent's response EXACTLY as it was provided - copy it verbatim.",
        "- Do NOT wrap it in code blocks (no ```markdown or ```).",
        "- Do NOT add any additional markdown syntax or formatting.",
        "- Do NOT modify, summarize, or rephrase the response.",
        "- Simply output the markdown-formatted response directly so it renders as a preview in the UI.",
    ],
)

# ============================================================================
# AgentOS Setup
# ============================================================================
agent_os = AgentOS(
    id="claim-review-os",
    description="Claim Review + Draft Response Agent - Multi-agent system for automated claim processing",
    agents=[claim_ingestor_agent, rule_checker_agent, draft_response_agent],
    teams=[claim_review_team],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app="main:app",
        reload=True,
        port=7777,
    )

