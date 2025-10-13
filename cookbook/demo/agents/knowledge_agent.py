"""Education Tutor - AI tutor that adapts to student's learning pace and style"""

from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb, SearchType
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")


class LearningAssessment(BaseModel):
    """Structured learning assessment"""

    student_level: str = Field(description="Current understanding level: beginner, intermediate, advanced")
    strengths: list[str] = Field(description="Topics student understands well")
    areas_for_improvement: list[str] = Field(description="Topics needing more practice")
    learning_style: str = Field(description="Identified learning style: visual, auditory, kinesthetic, reading")
    recommended_pace: str = Field(description="Recommended learning pace: slow, moderate, fast")
    next_topics: list[str] = Field(description="Suggested next topics to learn")
    practice_exercises: list[str] = Field(description="Recommended practice exercises")


# Create education knowledge base
education_knowledge = Knowledge(
    contents_db=db,
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="education_content",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

education_tutor = Agent(
    id="education-tutor",
    name="Adaptive Learning Tutor",
    session_id="education_tutor_session",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=education_knowledge,
    tools=[DuckDuckGoTools()],
    db=db,
    description=dedent("""\
        Personalized AI tutor that adapts to your learning pace and style.
        Remembers your progress, identifies knowledge gaps, and provides
        customized lessons, explanations, and practice exercises.\
    """),
    instructions=[
        "Assess student's current knowledge level and learning style",
        "Remember past lessons, progress, and areas of difficulty",
        "Adapt explanations to match student's understanding level",
        "Use multiple teaching approaches (visual, examples, analogies)",
        "Search knowledge base for educational content",
        "Break complex topics into manageable chunks",
        "Provide practice exercises and check understanding",
        "Celebrate progress and encourage persistence",
        "Identify and address knowledge gaps",
        "Adjust difficulty and pace based on student's responses",
        "Use the Socratic method to guide discovery",
        "Provide immediate, constructive feedback",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=15,
    add_datetime_to_context=True,
    output_schema=LearningAssessment,
    markdown=True,
)


async def load_education_knowledge():
    """Load educational resources into knowledge base"""
    try:
        print("\n📚 Loading educational resources into knowledge base...")
        # Example: Load sample educational content
        # In production, load curated curriculum content
        sample_education_content = """
        Python Programming Fundamentals:

        Variables and Data Types:
        - Variables store data values (numbers, strings, lists)
        - Use descriptive names (user_name, not x)
        - Python is dynamically typed (no type declaration needed)

        Control Flow:
        - if/elif/else for conditional logic
        - for loops iterate over sequences
        - while loops continue until condition is False
        - break exits loops early, continue skips iteration

        Functions:
        - Functions organize reusable code blocks
        - Define with def function_name(parameters):
        - Return values with return statement
        - Functions can have default parameter values

        Data Structures:
        - Lists: Ordered, mutable sequences [1, 2, 3]
        - Tuples: Ordered, immutable sequences (1, 2, 3)
        - Dictionaries: Key-value pairs {"name": "John"}
        - Sets: Unordered unique values {1, 2, 3}

        Best Practices:
        - Write clear, readable code with comments
        - Follow PEP 8 style guidelines
        - Handle errors with try/except blocks
        - Test your code thoroughly
        - Break complex problems into smaller functions

        Common Beginner Mistakes:
        - Forgetting colons after if/for/while/def statements
        - Incorrect indentation (use 4 spaces)
        - Modifying lists while iterating over them
        - Not handling exceptions properly
        """

        await education_knowledge.add_content_async(
            name="Python Tutorial",
            text_content=sample_education_content,
            skip_if_exists=True,
        )
        print("✅ Education knowledge base loaded successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not load education knowledge base: {e}")
