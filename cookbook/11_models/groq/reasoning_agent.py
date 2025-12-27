from agno.agent import Agent
from agno.models.groq import Groq

# Create a reasoning agent that uses:
# - `deepseek-r1-distill-llama-70b` as the reasoning model
# - `llama-3.3-70b-versatile` to generate the final response
reasoning_agent = Agent(
    model=Groq(id="llama-3.3-70b-versatile"),
    reasoning_model=Groq(
        id="deepseek-r1-distill-llama-70b", temperature=0.6, max_tokens=1024, top_p=0.95
    ),
)

# Prompt the agent to solve the problem
reasoning_agent.print_response("Is 9.11 bigger or 9.9?", stream=True)
