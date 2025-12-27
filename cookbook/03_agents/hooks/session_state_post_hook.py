"""Example demonstrating how to use a post_hook to update the session_state.

We will create a function that extract a list of topics discussed in the conversation, and keep them in the session state.
We will use the function as a post-hook, to run it after every run of the agent.
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutput
from pydantic import BaseModel, Field


class ConversationTopics(BaseModel):
    topics: List[str] = Field(description="Topics discussed in the conversation")


# This will be our post-hook function
def track_conversation_topics(run_context: RunContext, run_output: RunOutput) -> None:
    """Simple post-hook function to track conversation topics in the session state"""

    # Initialize the session state if it doesn't exist yet
    if run_context.session_state is None:
        run_context.session_state = {"topics": []}
    elif run_context.session_state.get("topics") is None:
        run_context.session_state["topics"] = []

    # Setup an Agent to get the topics discussed in the conversation
    topics_analyzer_agent = Agent(
        name="Topics Analyzer",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions=[
            "Your task is to analyze a conversation and extract the topics discussed."
            "You will be presented with a part of a conversation between a user and an agent."
            "You need to extract the topics discussed in the interaction."
            "Be concise and brief. Topics should be one or two words, and only want the one or two main topics."
            "Respond just with the list of topics, no other text or explanation."
        ],
        output_schema=ConversationTopics,
    )

    # Run the Agent to get the topics discussed in the conversation
    response = topics_analyzer_agent.run(
        input=f"What are the topics discussed in the following conversation?"
        f"User: {run_output.input.input_content}"  # type: ignore
        f"Agent: {run_output.content}",
    )

    # Update the session state to track the topics discussed in the conversation
    run_context.session_state["topics"].extend(response.content.topics)  # type: ignore


# Create a simple agent and equip it with our post-hook
agent = Agent(
    name="Simple Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    post_hooks=[track_conversation_topics],
    db=SqliteDb(db_file="test.db"),
)

agent.print_response(
    input="I want to know more about AI Agents.",
    session_id="topics_analyzer_session",
)
print(
    f"Current session state, after the first run: {agent.get_session_state(session_id='topics_analyzer_session')}"
)

agent.print_response(
    input="I also want to know more about Agno, the framework to build AI Agents.",
    session_id="topics_analyzer_session",
)
print(
    f"Current session state, after the second run: {agent.get_session_state(session_id='topics_analyzer_session')}"
)
