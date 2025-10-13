"""Healthcare Symptom Checker Team - Multi-agent team for symptom analysis and health recommendations"""

from textwrap import dedent

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai.chat import OpenAIChat
from agno.run.team import TeamRunInput
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb, SearchType
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")


class HealthAssessment(BaseModel):
    """Structured health assessment"""

    urgency_level: str = Field(
        description="Urgency: emergency, urgent, moderate, low"
    )
    possible_conditions: list[str] = Field(
        description="Possible conditions based on symptoms"
    )
    recommendations: list[str] = Field(description="Recommended actions")
    red_flags: list[str] = Field(description="Warning signs to watch for")
    self_care_tips: list[str] = Field(description="Self-care recommendations")
    when_to_see_doctor: str = Field(description="When to seek medical attention")
    disclaimer: str = Field(
        default="This is educational information only. Always consult a qualified healthcare professional for medical advice.",
        description="Medical disclaimer",
    )


def validate_health_input(run_input: TeamRunInput, team: Team) -> None:
    """Pre-hook: Ensure health queries are appropriate and safe"""
    query = run_input.input_content.lower()

    # Flag emergency situations
    emergency_keywords = [
        "chest pain",
        "difficulty breathing",
        "severe bleeding",
        "unconscious",
        "seizure",
        "stroke",
        "heart attack",
        "severe allergic",
        "poisoning",
    ]

    if any(keyword in query for keyword in emergency_keywords):
        raise InputCheckError(
            "⚠️  MEDICAL EMERGENCY DETECTED: Please call emergency services (911) immediately. This AI assistant cannot provide emergency medical care.",
            check_trigger="EMERGENCY_MEDICAL",
        )


# Create medical knowledge base
medical_knowledge = Knowledge(
    contents_db=db,
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="medical_info",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

triage_nurse = Agent(
    name="Triage Nurse",
    role="Initial symptom assessment and triage",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=medical_knowledge,
    description="Virtual triage nurse for initial symptom assessment (educational purposes only)",
    instructions=[
        "Assess symptoms and determine urgency level",
        "Ask relevant follow-up questions about symptoms",
        "Search medical knowledge base for information",
        "Identify potential red flags or warning signs",
        "Provide initial guidance on urgency and next steps",
        "Remember past symptom history and assessments",
        "Track symptom progression over time",
        "Always include medical disclaimer",
        "Direct to emergency services if needed",
        "This is educational information only - not medical diagnosis",
    ],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=8,
    add_datetime_to_context=True,
    db=db,
    output_schema=HealthAssessment,
    markdown=True,
)

health_specialist = Agent(
    name="Health Specialist",
    role="Detailed health information and recommendations",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=medical_knowledge,
    description="Health information specialist providing educational content",
    instructions=[
        "Provide detailed health information based on symptoms",
        "Reference medical knowledge base for accuracy",
        "Explain possible conditions in understandable language",
        "Provide evidence-based self-care recommendations",
        "Suggest when professional medical attention is needed",
        "Include preventive care advice",
        "Remember past health assessments and recommendations",
        "Track health patterns and recurring symptoms",
        "Always emphasize this is educational, not medical advice",
        "Recommend consulting healthcare professionals",
    ],
    tools=[DuckDuckGoTools()],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

healthcare_team = Team(
    id="healthcare-symptom-checker-team",
    name="Healthcare Symptom Checker Team",
    session_id="healthcare_checker_session",
    model=OpenAIChat(id="gpt-4o"),
    members=[triage_nurse, health_specialist],
    db=db,
    pre_hooks=[validate_health_input],
    description=dedent("""\
        Educational health information system that provides symptom analysis,
        health recommendations, and guidance on when to seek medical care.
        Features memory to track symptom progression and health patterns over time.
        FOR EDUCATIONAL PURPOSES ONLY - NOT A SUBSTITUTE FOR PROFESSIONAL MEDICAL ADVICE.\
    """),
    instructions=[
        "First, use Triage Nurse to assess urgency and gather symptom details",
        "Then, use Health Specialist to provide detailed health information",
        "Remember past symptom assessments and track progression",
        "Reference previous health information for context",
        "Always include prominent medical disclaimer",
        "Direct to emergency services for emergency situations",
        "Recommend consulting healthcare professionals for diagnosis",
        "Provide evidence-based educational information only",
        "Be empathetic and clear in communication",
    ],
    show_members_responses=True,
    markdown=True,
)


async def load_medical_knowledge():
    """Load medical information into knowledge base"""
    try:
        print("\n📚 Loading medical information into knowledge base...")
        # Example: Load sample medical information
        # In production, load from verified medical sources
        sample_medical_content = """
        Common Symptoms and When to Seek Care:

        Urgent Care Situations:
        - High fever (over 103°F/39.4°C) lasting more than 3 days
        - Persistent vomiting or diarrhea causing dehydration
        - Severe headache with vision changes
        - Difficulty breathing or shortness of breath
        - Severe abdominal pain

        Self-Care Guidelines:
        - Stay hydrated with water and electrolyte drinks
        - Get adequate rest (7-9 hours for adults)
        - Manage mild pain with over-the-counter medication
        - Monitor temperature and symptoms
        - Wash hands frequently to prevent illness spread

        When to See a Doctor:
        - Symptoms persisting longer than 7-10 days
        - Worsening symptoms despite self-care
        - New or unusual symptoms appearing
        - Chronic condition changes
        - Medication side effects

        Prevention Tips:
        - Regular exercise (150 minutes per week)
        - Balanced diet with fruits and vegetables
        - Adequate sleep and stress management
        - Regular health screenings
        - Stay up-to-date with vaccinations

        DISCLAIMER: This is educational information only. Always consult qualified healthcare professionals for medical advice.
        """

        await medical_knowledge.add_content_async(
            name="General Health Info",
            text_content=sample_medical_content,
            skip_if_exists=True,
        )
        print("✅ Medical knowledge base loaded successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not load medical knowledge base: {e}")
