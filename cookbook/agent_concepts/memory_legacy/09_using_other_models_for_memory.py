"""🎓 StudyScout - Your AI-Powered Learning Companion!

This advanced example shows how to create a sophisticated educational assistant
that leverages multiple AI models for enhanced memory and personalized learning.
The agent combines long-term memory, intelligent classification, and dynamic
summarization to deliver an adaptive learning experience that grows with the user.

Key Features:
- Personalized learning paths based on user interests and goals
- Long-term memory to track progress and preferences
- Intelligent content curation from multiple sources
- Interactive quizzes and assessments
- Resource recommendations (articles, videos, courses)

Example prompts to try:
- "Create a 3-month learning path for becoming a full-stack developer"
- "Explain quantum computing using gaming analogies based on my interests"
- "Quiz me on world history, focusing on the Renaissance period"
- "Find advanced machine learning resources matching my current skill level"
- "Help me prepare for the AWS Solutions Architect certification"

Run: `pip install groq agno` to install the dependencies
"""

from textwrap import dedent
from typing import List, Optional

import typer
from agno.agent import Agent, AgentMemory
from agno.memory.classifier import MemoryClassifier
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.memory.manager import MemoryManager
from agno.memory.summarizer import MemorySummarizer
from agno.models.groq import Groq
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.youtube import YouTubeTools
from rich import print

# Initialize storage components
agent_storage = SqliteAgentStorage(table_name="study_sessions", db_file="tmp/agents.db")
memory_db = SqliteMemoryDb(
    table_name="study_memory",
    db_file="tmp/agent_memory.db",
)


def study_agent(
    user_id: Optional[str] = typer.Argument(None, help="User ID for the study session"),
):
    """
    Initialize and run the StudyScout agent with the specified user ID.
    If no user ID is provided, prompt for one.
    """
    # Get user ID if not provided as argument
    if user_id is None:
        user_id = typer.prompt("Enter your user ID", default="default_user")

    session_id: Optional[str] = None

    # Ask the user if they want to start a new session or continue an existing one
    new = typer.confirm("Do you want to start a new study session?")

    if not new:
        existing_sessions: List[str] = agent_storage.get_all_session_ids(user_id)
        if len(existing_sessions) > 0:
            print("\nExisting sessions:")
            for i, session in enumerate(existing_sessions, 1):
                print(f"{i}. {session}")
            session_idx = typer.prompt(
                "Choose a session number to continue (or press Enter for most recent)",
                default=1,
            )
            try:
                session_id = existing_sessions[int(session_idx) - 1]
            except (ValueError, IndexError):
                session_id = existing_sessions[0]
        else:
            print("No existing sessions found. Starting a new session.")

    agent = Agent(
        name="StudyScout",
        user_id=user_id,
        session_id=session_id,
        model=Groq(id="llama-3.3-70b-versatile"),
        memory=AgentMemory(
            db=memory_db,
            create_user_memories=True,
            update_user_memories_after_run=True,
            classifier=MemoryClassifier(
                model=Groq(id="llama-3.3-70b-versatile"),
            ),
            summarizer=MemorySummarizer(
                model=Groq(id="llama-3.3-70b-versatile"),
            ),
            manager=MemoryManager(
                model=Groq(id="llama-3.3-70b-versatile"),
                db=memory_db,
                user_id=user_id,
            ),
        ),
        storage=agent_storage,
        tools=[DuckDuckGoTools(), YouTubeTools()],
        description=dedent("""\
        You are StudyScout, an expert educational mentor with deep expertise in personalized learning! 📚

        Your mission is to be an engaging, adaptive learning companion that helps users achieve their
        educational goals through personalized guidance, interactive learning, and comprehensive resource curation.
        """),
        instructions=dedent("""\
        Follow these steps for an optimal learning experience:

        1. Initial Assessment
        - Learn about the user's background, goals, and interests
        - Assess current knowledge level
        - Identify preferred learning styles

        2. Learning Path Creation
        - Design customized study plans, use DuckDuckGo to find resources
        - Set clear milestones and objectives
        - Adapt to user's pace and schedule

        3. Content Delivery
        - Break down complex topics into digestible chunks
        - Use relevant analogies and examples
        - Connect concepts to user's interests
        - Provide multi-format resources (text, video, interactive)

        4. Resource Curation
        - Find relevant learning materials using DuckDuckGo
        - Recommend quality educational content
        - Share community learning opportunities
        - Suggest practical exercises

        Your teaching style:
        - Be encouraging and supportive
        - Use emojis for engagement (📚 ✨ 🎯)
        - Incorporate interactive elements
        - Provide clear explanations
        - Use memory to personalize interactions
        - Adapt to learning preferences
        - Include progress celebrations
        - Offer study technique tips

        Remember to:
        - Keep sessions focused and structured
        - Provide regular encouragement
        - Celebrate learning milestones
        - Address learning obstacles
        - Maintain learning continuity\
        """),
        additional_context=dedent(f"""\
        - User ID: {user_id}
        - Session Type: {"New Session" if session_id is None else "Continuing Session"}
        - Available Tools: Web Search, YouTube Resources
        - Memory System: Active
        """),
        add_history_to_messages=True,
        num_history_responses=3,
        show_tool_calls=True,
        read_chat_history=True,
        markdown=True,
    )

    print("\n📚 Welcome to StudyScout - Your Personal Learning Companion! 🎓")
    if session_id is None:
        session_id = agent.session_id
        if session_id is not None:
            print(f"[bold green]Started New Study Session: {session_id}[/bold green]\n")
        else:
            print("[bold green]Started New Study Session[/bold green]\n")
    else:
        print(f"[bold blue]Continuing Previous Session: {session_id}[/bold blue]\n")

    # Runs the agent as a command line application
    agent.cli_app(markdown=True, stream=True)


if __name__ == "__main__":
    typer.run(study_agent)

"""
Example Usage:

1. Start a new learning session:
   ```bash
   python 03_using_other_models_for_memory.py
   ```

2. Continue with specific user ID:
   ```bash
   python 03_using_other_models_for_memory.py "learner_123"
   ```

Advanced Learning Scenarios:

Technical Skills:
1. "Guide me through learning system design principles"
2. "Help me master Python data structures and algorithms"
3. "Create a DevOps learning pathway for beginners"
4. "Teach me about cloud architecture patterns"

Academic Subjects:
1. "Explain organic chemistry reactions using cooking analogies"
2. "Help me understand advanced statistics concepts"
3. "Break down quantum mechanics principles"
4. "Guide me through macroeconomics theories"

Professional Development:
1. "Prepare me for product management interviews"
2. "Create a data science portfolio development plan"
3. "Design a public speaking improvement program"
4. "Build a cybersecurity certification roadmap"

Language Learning:
1. "Create an immersive Japanese learning experience"
2. "Help me practice business English scenarios"
3. "Design a Spanish conversation practice routine"
4. "Prepare me for the IELTS academic test"

Creative Skills:
1. "Guide me through digital art fundamentals"
2. "Help me develop creative writing techniques"
3. "Create a music theory learning progression"
4. "Design a UI/UX design learning path"
"""
