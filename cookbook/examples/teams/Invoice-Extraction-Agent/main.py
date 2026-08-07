from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.team import Team
from agno.models.google import Gemini
from agents import parser_agent, field_extractor_agent, validator_agent

# Team-based invoice extraction: Parser → Extractor → Validator
invoice_team = Team(
    name="Invoice Extraction",
    description="Extract structured invoice data from uploaded PDF files. Upload a PDF invoice to get normalized JSON output.",
    members=[parser_agent, field_extractor_agent, validator_agent],
    model=Gemini(id="gemini-2.0-flash"),
    instructions="""You are the Invoice Extraction coordinator.

    WORKFLOW:
    1) If files are present, delegate to "parser-agent" with the files.
    2) Delegate parser response to "extractor-agent".
    3) Delegate extractor response to "validator-agent".
    4) Return the validator response as your final output. Do NOT check for files again after delegations.

    IMPORTANT: After completing all delegations, return the validator output directly. Do not ask about files or check for files - the validator output IS the result.
    """,
    system_message="""Process files through parser-agent → extractor-agent → validator-agent. Return the validator output as final result.""",
    send_media_to_model=True,
    db=SqliteDb(session_table="team_session", db_file="tmp/teams.db"),
)

# Expose agents and team via AgentOS (accessible via /teams API endpoint)
agent_os = AgentOS(
    agents=[parser_agent, field_extractor_agent, validator_agent],
    teams=[invoice_team]
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="main:app", reload=True)


