import chainlit as cl
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai.chat import OpenAIChat

# Global variables
agent = None


@cl.on_chat_start
async def on_chat_start():
    """Initialize the agent when a new chat session starts."""
    # Create a unique database per session
    db = InMemoryDb()

    agent = Agent(
        model=OpenAIChat(
            id="gpt-4o",
        ),
        db=db,
        add_history_to_context=True,
        num_history_runs=5,
        stream=True,
        markdown=True,
        telemetry=False,
    )

    # Store the agent in the session
    cl.user_session.set("agent", agent)


@cl.on_message
async def on_message(message: cl.Message):
    # Get the agent from the session
    agent = cl.user_session.get("agent")

    response_msg = cl.Message(content="")
    await response_msg.send()

    async for event in agent.arun(message.content, stream=True):
        response_msg.content += event.content
        await response_msg.update()


if __name__ == "__main__":
    from chainlit.cli import run_chainlit

    run_chainlit(__file__)
