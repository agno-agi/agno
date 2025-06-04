from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.groq import Groq

deepseek_plus_claude = Agent(
    model=Claude(id="claude-3-7-sonnet-20250219"),
    reasoning_model=Groq(
        id="deepseek-r1-distill-llama-70b", temperature=0.6, max_tokens=1024, top_p=0.95
    ),
)
deepseek_plus_claude.print_response("9.11 and 9.9 -- which is bigger?", stream=True)
