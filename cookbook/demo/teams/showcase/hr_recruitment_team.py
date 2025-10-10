"""HR Recruitment Assistant Team - Multi-agent team for resume screening and candidate evaluation"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

from shared.database import db


class CandidateEvaluation(BaseModel):
    """Structured candidate evaluation"""

    candidate_name: str
    overall_score: float = Field(description="Score from 0.0 to 10.0")
    strengths: list[str] = Field(description="Key strengths and qualifications")
    weaknesses: list[str] = Field(description="Areas of concern or gaps")
    technical_skills_score: float = Field(description="Technical skills score 0-10")
    experience_score: float = Field(description="Experience relevance score 0-10")
    culture_fit_score: float = Field(description="Culture fit score 0-10")
    recommendation: str = Field(
        description="Recommendation: strong_hire, hire, maybe, no_hire"
    )
    interview_questions: list[str] = Field(description="Suggested interview questions")
    next_steps: str = Field(description="Recommended next steps")


resume_screener = Agent(
    name="Resume Screener",
    role="Initial resume screening and qualification check",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert at quickly evaluating resumes for required qualifications and red flags",
    instructions=[
        "Review resume for required qualifications and experience",
        "Check for employment gaps and inconsistencies",
        "Evaluate education and certifications",
        "Assess career progression and growth",
        "Flag any red flags or concerns",
        "Provide initial screening recommendation",
        "Remember company hiring criteria and preferences",
        "Track successful candidate patterns",
    ],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    db=db,
    output_schema=CandidateEvaluation,
    markdown=True,
)

skills_evaluator = Agent(
    name="Skills Evaluator",
    role="Deep technical and soft skills assessment",
    model=OpenAIChat(id="gpt-4o"),
    description="Specialist in evaluating technical competencies and soft skills",
    instructions=[
        "Evaluate technical skills against job requirements",
        "Assess depth and breadth of expertise",
        "Review project experience and accomplishments",
        "Evaluate soft skills: communication, leadership, teamwork",
        "Consider learning agility and growth potential",
        "Provide detailed skills assessment",
        "Remember role-specific skill requirements",
        "Track skill trends and emerging technologies",
    ],
    tools=[DuckDuckGoTools()],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=8,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

culture_fit_assessor = Agent(
    name="Culture Fit Assessor",
    role="Evaluates cultural alignment and team fit",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert in assessing candidate alignment with company culture and values",
    instructions=[
        "Evaluate alignment with company values and culture",
        "Assess team collaboration and communication style",
        "Consider work style and preferences",
        "Evaluate motivation and career goals",
        "Assess adaptability and change management",
        "Provide culture fit assessment",
        "Remember company culture attributes and values",
        "Track team dynamics and successful hires",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

hr_recruitment_team = Team(
    id="hr-recruitment-team",
    name="HR Recruitment Assistant Team",
    session_id="hr_recruitment_session",
    model=OpenAIChat(id="gpt-4o"),
    members=[resume_screener, skills_evaluator, culture_fit_assessor],
    db=db,
    description=dedent("""\
        AI-powered recruitment team that screens resumes, evaluates technical
        and soft skills, assesses culture fit, and provides structured hiring
        recommendations. Features comprehensive memory to track hiring patterns,
        successful candidates, and evolving role requirements.\
    """),
    instructions=[
        "First, use Resume Screener to check basic qualifications",
        "Then, use Skills Evaluator for deep technical assessment",
        "Next, use Culture Fit Assessor for team and culture alignment",
        "Synthesize all assessments into a comprehensive evaluation",
        "Remember past successful hires and their characteristics",
        "Track role evolution and changing requirements",
        "Reference previous evaluations for consistency",
        "Provide clear hiring recommendation with confidence level",
        "Generate relevant interview questions to probe deeper",
        "Be objective and avoid bias in all assessments",
    ],
    show_members_responses=True,
    markdown=True,
)
