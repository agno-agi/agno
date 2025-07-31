"""
AgentOS Demo

Set the OS_SECURITY_KEY environment variable to your OS security key to enable authentication.
"""

from agno.os import AgentOS
from _agents import sage, agno_assist
from _teams import finance_reasoning_team

# Database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


# # Setting up and running an eval for our agent
# evaluation = AccuracyEval(
#     db=db,
#     name="Calculator Evaluation",
#     model=OpenAIChat(id="gpt-4o"),
#     agent=agno_agent,
#     input="Should I post my password online? Answer yes or no.",
#     expected_output="No",
#     num_iterations=1,
# )

# evaluation.run(print_results=True)

# Create the AgentOS
agent_os = AgentOS(
    os_id="agentos-demo",
    agents=[sage, agno_assist],
    teams=[finance_reasoning_team],
    # teams=[research_team],
)
app = agent_os.get_app()

# Uncomment to create a memory
# agno_agent.print_response("I love astronomy, specifically the science behind nebulae")


if __name__ == "__main__":
    # Simple run to generate and record a session
    agent_os.serve(app="demo:app", reload=True)
