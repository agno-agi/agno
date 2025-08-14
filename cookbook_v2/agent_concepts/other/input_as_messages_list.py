from agno.agent import Agent, Message

Agent().print_response(
    input=[
        Message(
            role="user",
            content=[
                {"type": "text", "text": "Hi! My name is John."},
            ],
        ),
        Message(
            role="user",
            content=[
                {"type": "text", "text": "What are you capable of?"},
            ],
        ),
    ],
    stream=True,
    markdown=True,
)
