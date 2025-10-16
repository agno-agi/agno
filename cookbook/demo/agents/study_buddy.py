"""
Study Buddy - Comprehensive AI agent with RAG, validation hooks, and tool monitoring
"""

import json
from textwrap import dedent
from typing import Iterator

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.exceptions import InputCheckError
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai.chat import OpenAIChat
from agno.run.agent import RunInput
from agno.tools import FunctionCall, tool
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb, SearchType
from pydantic import BaseModel, Field

# ============================================================================
# Database Configuration
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url, id="study_buddy_db")


class LearningAssessment(BaseModel):
    """Structured learning assessment"""

    student_level: str = Field(
        description="Current understanding level: beginner, intermediate, advanced"
    )
    strengths: list[str] = Field(description="Topics student understands well")
    areas_for_improvement: list[str] = Field(description="Topics needing more practice")
    learning_style: str = Field(
        description="Identified learning style: visual, auditory, kinesthetic, reading"
    )
    recommended_pace: str = Field(
        description="Recommended learning pace: slow, moderate, fast"
    )
    next_topics: list[str] = Field(description="Suggested next topics to learn")
    practice_exercises: list[str] = Field(description="Recommended practice exercises")


# ============================================================================
# Input Validation Hooks
# ============================================================================


def validate_education_query(run_input: RunInput, agent: Agent) -> None:
    """
    INPUT VALIDATION HOOK: Pre-hook to validate educational queries

    Demonstrates:
    - Input validation before processing
    - Emergency detection for safety-critical queries
    - Spam and abuse prevention
    """
    query = run_input.input_content.lower()

    # Check for minimum query length
    if len(query.strip()) < 3:
        raise InputCheckError(
            "Please provide a more detailed question or topic to help me assist you better.",
            check_trigger="INPUT_TOO_SHORT",
        )

    # Detect emergency/crisis situations (redirect to appropriate resources)
    crisis_keywords = [
        "suicide",
        "kill myself",
        "end my life",
        "want to die",
        "self harm",
        "hurt myself",
    ]

    if any(keyword in query for keyword in crisis_keywords):
        raise InputCheckError(
            " CRISIS SUPPORT NEEDED: Please contact a crisis helpline immediately:\n"
            "• National Suicide Prevention Lifeline: 988 (US)\n"
            "• Crisis Text Line: Text HOME to 741741\n"
            "• International Association for Suicide Prevention: https://www.iasp.info/resources/Crisis_Centres/\n\n"
            "I'm an educational AI and not equipped to provide crisis support. Please reach out to trained professionals who can help.",
            check_trigger="CRISIS_DETECTED",
        )

    # Detect inappropriate educational requests
    inappropriate_keywords = [
        "homework answers",
        "cheat",
        "test answers",
        "exam solutions",
    ]
    if any(keyword in query for keyword in inappropriate_keywords):
        raise InputCheckError(
            "I'm here to help you learn and understand concepts, not to provide direct answers to homework or tests. "
            "Let me help you understand the underlying concepts instead!",
            check_trigger="ACADEMIC_INTEGRITY",
        )


# ============================================================================
# Tool Hooks (Monitoring & Logging)
# ============================================================================


def log_knowledge_query(fc: FunctionCall):
    """
    TOOL HOOK: Pre-hook to log knowledge base queries

    Demonstrates:
    - Monitoring tool usage for analytics
    - Tracking what knowledge is being accessed
    - Audit trail for knowledge retrieval
    """
    if fc.arguments:
        print(f"   Query Details: {json.dumps(fc.arguments, indent=2)[:200]}")


def validate_knowledge_result(fc: FunctionCall):
    """
    TOOL HOOK: Post-hook to validate and enrich knowledge base results

    Demonstrates:
    - Result validation and quality checks
    - Adding metadata to responses
    - Tracking successful knowledge retrievals
    """
    if fc.result:
        result_size = len(str(fc.result))
        print(f"   Result Size: {result_size} characters")
        if result_size < 50:
            print("   ⚠️  Warning: Result may be incomplete or empty")


# ============================================================================
# Custom Tools with Hooks
# ============================================================================


@tool(pre_hook=log_knowledge_query, post_hook=validate_knowledge_result)
def search_educational_resources(topic: str, num_results: int = 3) -> Iterator[str]:
    """
    Search for educational resources and learning materials.

    This tool demonstrates tool hooks in action - the pre/post hooks
    monitor and validate all searches for analytics and quality assurance.

    Args:
        topic: Educational topic to search for
        num_results: Number of resources to return (default: 3)

    Returns:
        Iterator yielding educational resources as JSON strings
    """
    # This is a demonstration tool - in production, integrate with
    # educational content databases, learning management systems, etc.
    educational_resources = {
        "python": [
            {
                "title": "Python Official Tutorial",
                "url": "https://docs.python.org/3/tutorial/",
                "description": "Comprehensive official Python tutorial covering all basics",
                "level": "beginner-intermediate",
            },
            {
                "title": "Real Python Tutorials",
                "url": "https://realpython.com/",
                "description": "Practical Python tutorials with code examples",
                "level": "all levels",
            },
            {
                "title": "Python for Everybody",
                "url": "https://www.py4e.com/",
                "description": "Free course materials for learning Python programming",
                "level": "beginner",
            },
        ],
        "machine learning": [
            {
                "title": "Andrew Ng's ML Course",
                "url": "https://www.coursera.org/learn/machine-learning",
                "description": "Classic introductory course on machine learning",
                "level": "intermediate",
            },
            {
                "title": "Fast.ai Practical Deep Learning",
                "url": "https://course.fast.ai/",
                "description": "Practical deep learning for coders",
                "level": "intermediate",
            },
        ],
    }

    # Find matching resources
    topic_lower = topic.lower()
    results = []

    for key, resources in educational_resources.items():
        if key in topic_lower or topic_lower in key:
            results.extend(resources[:num_results])

    if results:
        for resource in results[:num_results]:
            yield json.dumps(resource, indent=2)
    else:
        yield json.dumps(
            {
                "message": f"No specific resources found for '{topic}'. Try web search for broader results.",
                "suggestion": "Use DuckDuckGo search tool for more comprehensive results",
            }
        )


# ============================================================================
# Knowledge Base Configuration
# ============================================================================

# Create education knowledge base
education_knowledge = Knowledge(
    contents_db=db,
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="study_buddy_education",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

study_buddy = Agent(
    id="study-buddy",
    name="Study Buddy",
    session_id="study_buddy_session",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=education_knowledge,  # RAG with vector database
    tools=[
        search_educational_resources,  # Custom tool with hooks
        DuckDuckGoTools(),  # Web search for supplementary info
    ],
    db=db,
    pre_hooks=[validate_education_query],  # INPUT VALIDATION HOOK
    description=dedent("""\
        Comprehensive AI knowledge expert with advanced learning capabilities.

        Features:
        • 📚 Knowledge Base (RAG) with vector search for accurate information
        • 🔍 Web search for supplementary and current information
        • ✅ Input validation for safety and quality
        • 📊 Tool monitoring for analytics and quality assurance
        • 🧠 Adaptive learning based on your progress and style
        • 💾 Memory of past interactions and learning patterns

        Perfect for education, research, and general knowledge queries with
        built-in safety checks and monitoring.\
    """),
    instructions=[
        "You are a comprehensive knowledge expert with access to multiple information sources",
        "",
        "CORE CAPABILITIES:",
        "- Search the knowledge base (RAG) for stored educational content",
        "- Use search_educational_resources tool to find learning materials",
        "- Use DuckDuckGo for current information and broader research",
        "- Respond naturally with clear explanations, examples, and guidance",
        "",
        "TEACHING APPROACH:",
        "- Assess student's current knowledge level and learning style",
        "- Adapt explanations to match understanding level",
        "- Use multiple teaching approaches (visual, examples, analogies)",
        "- Break complex topics into manageable chunks",
        "- Provide practice exercises and check understanding",
        "- Use the Socratic method to guide discovery",
        "- Celebrate progress and encourage persistence",
        "",
        "MEMORY & PERSONALIZATION:",
        "- Remember past lessons, progress, and areas of difficulty",
        "- Track learning patterns and preferences over time",
        "- Adapt difficulty and pace based on student responses",
        "- Identify and address knowledge gaps proactively",
        "",
        "QUALITY & SAFETY:",
        "- Always validate information from multiple sources",
        "- Provide immediate, constructive feedback",
        "- Maintain academic integrity (no homework answers)",
        "- Direct to appropriate resources for crisis situations",
        "",
        "NOTE: All your tool usage is monitored and logged for quality assurance",
    ],
    # MEMORY: Track learning progress over time
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=15,
    add_datetime_to_context=True,
    # Note: LearningAssessment schema available but not enforced - agent responds naturally
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
        print("Education knowledge base loaded successfully")
    except Exception as e:
        print(f" Warning: Could not load education knowledge base: {e}")
