from agno.agent import Agent
from agno.team import Team

team = Team(
    members=[
        Agent(
            name="Sarah",
            role="Data Researcher",
            instructions="Focus on gathering and analyzing data",
        ),
        Agent(
            name="Mike",
            role="Technical Writer",
            instructions="Create clear, concise summaries",
        ),
    ],
)

team.print_response(
    [
        {"type": "text", "text": "What's in this image?"},
        {
            "type": "image_url",
            "image_url": {
                "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg",
            },
        },
    ],
    stream=True,
    markdown=True,
)
