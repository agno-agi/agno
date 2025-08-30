import requests
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Audio
from agno.models.google import Gemini
from agno.team import Team

transcription_agent = Agent(
    name="Audio Transcriber",
    role="Transcribe audio conversations accurately",
    model=Gemini(id="gemini-2.0-flash-exp"),
    instructions=[
        "Transcribe audio with speaker identification",
        "Maintain conversation structure and flow",
    ],
)

sentiment_analyst = Agent(
    name="Sentiment Analyst",
    role="Analyze emotional tone and sentiment in conversations",
    model=Gemini(id="gemini-2.0-flash-exp"),
    instructions=[
        "Analyze sentiment for each speaker separately",
        "Identify emotional patterns and conversation dynamics",
        "Provide detailed sentiment insights",
    ],
)

# Create a team for collaborative audio sentiment analysis
sentiment_team = Team(
    name="Audio Sentiment Team",
    members=[transcription_agent, sentiment_analyst],
    model=Gemini(id="gemini-2.0-flash-exp"),
    instructions=[
        "Analyze audio sentiment with conversation memory.",
        "Audio Transcriber: First transcribe audio with speaker identification.",
        "Sentiment Analyst: Analyze emotional tone and conversation dynamics.",
    ],
    add_history_to_context=True,
    markdown=True,
    db=SqliteDb(
        session_table="audio_sentiment_team_sessions",
        db_file="tmp/audio_sentiment_team.db",
    ),
)

url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"

response = requests.get(url)
audio_content = response.content

sentiment_team.print_response(
    "Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.",
    audio=[Audio(content=audio_content)],
    stream=True,
)

sentiment_team.print_response(
    "What else can you tell me about this audio conversation?",
    stream=True,
)
