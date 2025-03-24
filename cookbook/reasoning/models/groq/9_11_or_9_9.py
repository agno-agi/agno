from agno.agent import Agent
from agno.models.groq import Groq

agent = Agent(
    model=Groq(
        id="deepseek-r1-distill-llama-70b", temperature=0.6, max_tokens=1024, top_p=0.95
    ),
    markdown=True,
)
agent.print_response("9.11 and 9.9 -- which is bigger?", stream=True)
