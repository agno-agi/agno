import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini
from agno.team import Team

transcription_specialist = Agent(
    name="Transcription Specialist",
    role="Convert audio to accurate text transcriptions",
    model=Gemini(id="gemini-2.0-flash-exp"),
    instructions=[
        "Transcribe audio with high accuracy",
        "Identify speakers clearly as Speaker A, Speaker B, etc.",
        "Maintain conversation flow and context",
    ],
)

content_analyzer = Agent(
    name="Content Analyzer",
    role="Analyze transcribed content for insights",
    model=Gemini(id="gemini-2.0-flash-exp"),
    instructions=[
        "Analyze transcription for key themes and insights",
        "Provide summaries and extract important information",
    ],
)

# Create a team for collaborative audio-to-text processing
audio_team = Team(
    name="Audio Analysis Team",
    model=Gemini(id="gemini-2.0-flash-exp"),
    members=[transcription_specialist, content_analyzer],
    instructions=[
        "Work together to transcribe and analyze audio content.",
        "Transcription Specialist: First convert audio to accurate text with speaker identification.",
        "Content Analyzer: Analyze transcription for insights and key themes.",
    ],
    markdown=True,
)

url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"

response = requests.get(url)
audio_content = response.content

audio_team.print_response(
    "Give a transcript of this audio conversation. Use speaker A, speaker B to identify speakers.",
    audio=[Audio(content=audio_content)],
    stream=True,
)
