import json
import os
import re
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools
from agno.tools.youtube import YouTubeTools
from agno.utils.log import logger
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
cwd = Path(__file__).parent.resolve()
scratch_dir = cwd.joinpath("scratch")
if not scratch_dir.exists():
    scratch_dir.mkdir(exist_ok=True, parents=True)


def learning_path_agent() -> Agent:
    """Instantiate and return the learning path curator agent."""
    return Agent(
        name="learning_path_agent",
        role=dedent("""You are an **AI tutor** specializing in creating structured, personalized learning plans for students.

        Your responsibilities:
        1. Analyze the **topic** the student wants to learn and its **depth** (Beginner, Intermediate, Advanced).
        2. Structure a **detailed daily learning schedule** for the specified duration.
        3. Include **relevant learning materials** from YouTube, Exa search, and books/articles.
        4. Break down complex topics into **manageable daily lessons**.
        5. Consider the student's **preferred format** (videos, articles, books).
        6. Adjust the plan to fit within the user's **daily time limit**.
        7. Provide **clear and actionable steps** each day.

        Expected Output Format:
        - Day 1: Topic Overview + Learning Materials (YouTube, Blogs, Books)
        - Day 2: Core Concepts + Examples
        - Day 3: Application + Hands-on Exercises
        - …
        - Final Day: Advanced Topics & Real-world Applications
        """),
        instructions=[
            "1. Use ExaSearch and YouTubeSearch to find **relevant learning resources**.",
            "2. Provide **concise but structured** day-wise learning breakdowns.",
            "3. Ensure the content follows a **logical progression** from basic to advanced concepts.",
            "4. Adapt learning paths based on the student’s time constraints and learning pace.",
            "5. Ensure content diversity (videos, articles, books) based on user preferences.",
        ],
        model=OpenAIChat(id="gpt-4o"),
        tools=[ExaTools(), YouTubeTools()],
        read_chat_history=True,
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        debug_mode=True,
        show_tool_calls=True,
    )


def get_quiz_agent():
    """Returns an AI-powered Quiz Agent."""
    return Agent(
        name="quiz_agent",
        role="""You are an AI Quiz Generator for an Adaptive Learning Tutor.

        **Responsibilities:**
        - Take the **learning path (all days)** and the **selected day** as input.
        - Generate **5 multiple-choice questions (MCQs)** based on that day's topic.
        - Provide **4 answer options per question**, with **1 correct answer**.
        - Format output as structured JSON for easy UI display.
        """,
        model=OpenAIChat(id="gpt-4o"),
        read_chat_history=False,
        add_history_to_messages=False,
    )


def extract_json_content(response_text):
    """Ensure the response contains a valid JSON array by extracting text between [ and ]"""
    match = re.search(r"\[\s*{.*?}\s*\]", response_text, re.DOTALL)  # Non-greedy match
    return match.group(0) if match else None  # Return extracted JSON or None


def generate_quiz(learning_path, day):
    """Generate a quiz based on the given learning path and day."""
    quiz_agent = get_quiz_agent()
    prompt = f"""
    Based on the following **learning path**, generate **5 multiple-choice questions**
    for **Day {day}** with 4 options each. Also, provide the correct answer for each.

    Learning Path:
    {learning_path}

    **Output must be in JSON format with the following structure:**
    [
        {{
            "question": "What is XYZ?",
            "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
            "correct_answer": "Option 2"
        }},
        ...
    ]
    """

    response = quiz_agent.run(prompt)
    logger.info(f"---*--- Response from quiz agent ---*--- \n{response.content}")
    json_text = extract_json_content(response.content)

    if json_text:
        try:
            quiz_json = json.loads(
                json_text
            )  # Convert string response into Python list
            logger.info(f"\n\nQuiz json: {quiz_json}")
            return quiz_json
        except json.JSONDecodeError:
            logger.error("❌ Error: Invalid JSON format")
            return []
    else:
        logger.error("❌ Error: No valid JSON found in response")
        return []
