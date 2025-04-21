from agno.agent import Agent
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel
from rich.pretty import pprint


@tool()
def answer_from_known_questions(agent: Agent, question: str) -> str:
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
    if agent.session_state is None:
        agent.session_state = {}

    if "last_answer" in agent.session_state:
        del agent.session_state["last_answer"]

    if question in faq:
        answer = Answer(answer=faq[question], original_question=question)
        agent.session_state["last_answer"] = answer
        return answer.answer
    else:
        return "I don't know the answer to that question."


q_and_a_agent = Agent(
    name="Q & A Agent",
    tools=[answer_from_known_questions, DuckDuckGoTools()],
    markdown=True,
    instructions="You are a Q & A agent that can answer questions from a list of known questions. If you don't know the answer, you can search the web.",
)

q_and_a_agent.print_response("What is the capital of France?", stream=True)

if "last_answer" in q_and_a_agent.session_state:
    pprint(q_and_a_agent.session_state["last_answer"])


q_and_a_agent.print_response("What is the capital of South Africa?", stream=True)
