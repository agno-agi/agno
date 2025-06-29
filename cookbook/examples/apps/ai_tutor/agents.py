import json
import os
import re
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools
from agno.utils.log import logger
from utils import extract_day_content
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


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
        ```
        # Learning Path: Topic

        ## Overview
        - Main learning objectives
        - Estimated completion time
        - Prerequisites (if any)

        ## Day 1:
        ### Learning Objectives:
        - Objective 1
        - Objective 2
        - ...

        ### Resources:
        - Resource 1
        - Resource 2
        - ...

        ### Hands-on:
        - Hands on tasks if any

        Repeat for each day in similar format...
        ```
        """),
        instructions=[
            "1. Use ExaTools search to find **relevant learning resources**.",
            "2. Provide **concise but structured** day-wise learning breakdowns.",
            "3. Ensure the content follows a **logical progression** from basic to advanced concepts.",
            "4. Adapt learning paths based on the student’s time constraints and learning pace.",
            "5. Ensure content diversity (videos, articles, books) based on user preferences.",
        ],
        model=OpenAIChat(id="gpt-4o"),
        tools=[ExaTools()],
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
        - Take the **learning path for a specific day** as input.
        - Generate **5 multiple-choice questions (MCQs)** based on that day's topic.
        - Provide **4 answer options per question**, with **1 correct answer**.
        - The questions should be related to that topic, asking in-depth questions to understand user's level of understanding.
        - Include explanations for why each answer is correct or incorrect.
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
    """
    Generate a quiz based on the given learning path and day.

    Args:
        learning_path: The full learning path content
        day: The day number to generate a quiz for

    Returns:
        List of quiz questions in JSON format
    """
    quiz_agent = get_quiz_agent()

    # Extract content for the specific day
    day_content = extract_day_content(learning_path, day)

    if not day_content:
        logger.error(f"Could not find content for Day {day}")
        day_content = learning_path

    prompt = f"""
    Generate **5 multiple-choice questions** for the following learning content.
    Include 1 easy question, 2 medium questions, and 2 difficult questions for comprehensive assessment.

    For each question, provide:
    1. The question text
    2. Four answer options
    3. The correct answer
    4. A brief explanation of why the correct answer is right
    5. A difficulty rating (easy, medium, difficult)

    Learning Content for Day {day}:
    {day_content}

    **Output must be in JSON format with the following structure:**
    [
        {{
            "question": "What is XYZ?",
            "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
            "correct_answer": "Option 2",
            "explanation": "Option 2 is correct because...",
            "difficulty": "medium"
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


def get_analysis_agent():
    """Returns an AI-powered Analysis Agent for quiz performance review."""
    return Agent(
        name="analysis_agent",
        role="""You are an AI Learning Analytics Expert for an Adaptive Learning System.

        **Responsibilities:**
        - Analyze quiz results data for a specific user and learning path.
        - Identify knowledge gaps and learning patterns.
        - Generate personalized recommendations to improve the learning path.
        - Create a supportive and encouraging performance report.
        - Suggest specific review areas based on quiz performance.
        """,
        model=OpenAIChat(id="gpt-4o"),
    )


def generate_quiz_report(user_id, day, score, quiz_analysis):
    """
    Generate a detailed report based on quiz performance.

    Args:
        user_id: The user's identifier
        day: The day number
        score: Overall quiz score (already calculated)
        quiz_analysis: List of analyzed questions with user answers and correctness

    Returns:
        A performance report with recommendations
    """
    analysis_agent = get_analysis_agent()

    # Count correct answers from the analysis
    correct_answers = sum(1 for q in quiz_analysis if q.get("is_correct"))
    total_questions = len(quiz_analysis)

    prompt = f"""
    Please analyze the following quiz results for user {user_id} on Day {day} and generate a comprehensive
    performance report with recommendations for further study.

    Quiz Score: {score}%
    Questions Correct: {correct_answers} out of {total_questions}

    Question Analysis:
    {json.dumps(quiz_analysis, indent=2)}

    Please include in your analysis:
    1. Overall performance summary
    2. Identified knowledge gaps or areas of weakness
    3. Strengths demonstrated in the quiz
    4. Specific recommendations for topics to review
    5. Encouragement and next steps

    Format your response as a structured report with clear sections and actionable recommendations.
    """

    response = analysis_agent.run(prompt)
    return response.content


def modify_learning_path(original_path, day, quiz_results):
    """
    Provide recommendations to modify a learning path based on quiz performance.

    Args:
        original_path: The original learning path content
        day: The day for which modification is needed
        quiz_results: Results from the quiz for that day

    Returns:
        Recommendations for learning path modifications
    """
    analysis_agent = get_analysis_agent()

    # Extract day content for context
    day_content = extract_day_content(original_path, day)

    if not day_content:
        logger.error(f"Could not find content for Day {day}")
        return "Could not find the specified day in the learning path."

    prompt = f"""
    Based on the user's quiz performance for Day {day}, please provide recommendations
    for modifying their learning approach. The user scored {quiz_results.get('score', 0)}%
    on the quiz.

    Current learning content for Day {day}:
    {day_content}

    Quiz Results:
    {json.dumps(quiz_results, indent=2)}

    Please provide:
    1. Analysis of which concepts the user struggled with
    2. Recommendations for additional resources they should review
    3. Suggestions for alternative learning approaches
    4. Next steps for their learning journey

    Format your response as clear recommendations that the user can follow.
    """

    response = analysis_agent.run(prompt)
    return response.content
