from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response("1 sentence news story from New York", stream=True)
