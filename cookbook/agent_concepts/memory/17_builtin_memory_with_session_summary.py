from agno.agent import Agent
from agno.memory.v2 import Memory, SessionSummarizer
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# You can also override the entire `system_message` for the session summarizer if you wanted
session_summarizer = SessionSummarizer(
    model=OpenAIChat(id="gpt-4o-mini"),
    additional_instructions="""
    Make the summary a points-wise list of a summarised version of each message in the conversation.
    """,
)

memory = Memory(
    summarizer=session_summarizer,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    # Set add_history_to_messages=true to add the previous chat history to the messages sent to the Model.
    add_history_to_messages=True,
    # Number of historical responses to add to the messages.
    num_history_runs=3,
    # Let the agent summarize the session after every run
    enable_session_summaries=True,
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner. Keep responses very short and concise.",
)

agent.print_response("Hello! How are you today?", stream=True)

agent.print_response("Explain what an LLM is.", stream=True)

agent.print_response(
    "I'm thinking about learning a new programming language. Any suggestions?",
    stream=True,
)

agent.print_response("Tell me an interesting fact about space.", stream=True)


# -*- Print the messages in the memory
pprint(
    [
        m.model_dump(include={"role", "content"})
        for m in agent.get_messages_for_session()
    ]
)

agent.print_response("What have we been talking about?", stream=True)

# -*- Print the messages used for the last response (only the last 3 is kept in history)
pprint([m.model_dump(include={"role", "content"}) for m in agent.run_response.messages])

# We can get the session summary from memory as well
session_summary = agent.get_session_summary()
pprint(session_summary)
