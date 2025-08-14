"""
This example demonstrates how to create a team with custom tools.

The team uses custom tools alongside agent tools to answer questions from a knowledge base
and fall back to web search when needed.
"""

from agno.agent import Agent
from agno.team.team import Team
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel
from rich.pretty import pprint


@tool()
def answer_from_known_questions(agent: Team, question: str) -> str:
    """Answer a question from a list of known questions

    Args:
        question: The question to answer

    Returns:
        The answer to the question
    """

    class Answer(BaseModel):
        answer: str
        original_question: str

    # FAQ knowledge base
    faq = {
        "What is the capital of France?": "Paris",
        "What is the capital of Germany?": "Berlin",
        "What is the capital of Italy?": "Rome",
        "What is the capital of Spain?": "Madrid",
        "What is the capital of Portugal?": "Lisbon",
        "What is the capital of Greece?": "Athens",
        "What is the capital of Turkey?": "Ankara",
    }
    
    # Initialize session state if needed
    if agent.session_state is None:
        agent.session_state = {}

    # Clear previous answer
    if "last_answer" in agent.session_state:
        del agent.session_state["last_answer"]

    # Check if question is in FAQ
    if question in faq:
        answer = Answer(answer=faq[question], original_question=question)
        agent.session_state["last_answer"] = answer
        return answer.answer
    else:
        return "I don't know the answer to that question."


# Create web search agent for fallback
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Create team with custom tool and agent members
team = Team(
    name="Q & A team", 
    members=[web_agent], 
    tools=[answer_from_known_questions]
)

# Test the team
team.print_response("What is the capital of France?", stream=True)

# Display the stored answer from session state
if "last_answer" in team.session_state:
    pprint(team.session_state["last_answer"])
