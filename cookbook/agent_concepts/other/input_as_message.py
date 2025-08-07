from agno.agent import Agent
from agno.models.message import Message
from agno.team import Team

# Create a research team
team = Team(
    name="Research Team",
    members=[
        Agent(name="Sarah", role="Data Researcher", instructions="Focus on gathering and analyzing data"),
        Agent(name="Mike", role="Technical Writer", instructions="Create clear, concise summaries"),
    ],
    stream=True,
    markdown=True,
)

team.print_response(
    Message(
        role="user",
        content=[
            {"type": "text", "text": "What's in this image?"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg",
                },
            },
        ],
    ),
    stream=True,
    markdown=True,
)