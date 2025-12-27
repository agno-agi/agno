"""Example demonstrating how to manipulate the session_state in a tool."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.run import RunContext
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel


@tool()
def answer_from_known_questions(question: str, run_context: RunContext) -> str:
    """Answer a question from a list of known questions

    Args:
        question: The question to answer

    Returns:
        The answer to the question
    """

    class Answer(BaseModel):
        answer: str
        original_question: str

    faq = {
        "What is the capital of France?": "Paris",
        "What is the capital of Germany?": "Berlin",
        "What is the capital of Italy?": "Rome",
        "What is the capital of Spain?": "Madrid",
        "What is the capital of Portugal?": "Lisbon",
        "What is the capital of Greece?": "Athens",
        "What is the capital of Turkey?": "Ankara",
    }

    if run_context.session_state is None:
        run_context.session_state = {}

    if "last_answer" in run_context.session_state:
        del run_context.session_state["last_answer"]

    if question in faq:
        answer = Answer(answer=faq[question], original_question=question)
        run_context.session_state["last_answer"] = answer.model_dump()
        return answer.answer
    else:
        return "I don't know the answer to that question."


# Set and run the Agent
q_and_a_agent = Agent(
    name="Q & A Agent",
    db=SqliteDb(db_file="tmp/q_and_a_agent.db"),
    tools=[answer_from_known_questions, DuckDuckGoTools()],
    markdown=True,
    instructions="You are a Q & A agent that can answer questions from a list of known questions. If you don't know the answer, you can search the web.",
)

# First run
q_and_a_agent.print_response("What is the capital of France?", stream=True)

# Print session_state
session_state = q_and_a_agent.get_session_state()
if session_state and "last_answer" in session_state:
    print(f"\nSession state after first run -> {session_state['last_answer']}\n")


# Second run
q_and_a_agent.print_response("What is the capital of Germany?", stream=True)

# Print session_state
session_state = q_and_a_agent.get_session_state()
if session_state and "last_answer" in session_state:
    print(f"\nSession state after second run -> {session_state['last_answer']}\n")
