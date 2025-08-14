from agno.agent import Agent
from agno.models.message import Message

Agent().print_response(input="Also, please summarize the key findings in bullet points for my slides.",
    input=[
        Message(
            role="user",
            content="I'm preparing a presentation for my company about renewable energy adoption.",
        ),
        Message(
            role="assistant",
            content="I'd be happy to help with your renewable energy presentation. What specific aspects would you like me to focus on?",
        ),
        Message(
            role="user",
            content="Could you research the latest solar panel efficiency improvements in 2024?",
        ),
    ],
    markdown=True,
)
