import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.cognee import CogneeTools

# your .env file should have the following variables:
# OPENAI_API_KEY=your_openai_api_key
# LLM_API_KEY=your_openai_api_key
# or
api_key = "<your_openai_api_key>"
os.environ['OPENAI_API_KEY'] = api_key
os.environ["LLM_API_KEY"] = api_key

def main():
    cognee_tools = CogneeTools()
    llm = OpenAIChat(id="gpt-5-mini")

    agent = Agent(
        model=llm,
        tools=[cognee_tools],
        instructions="You are a helpful assistant with persistent memory."
    )

    agent.print_response("Remember: I am John Doe and I like to play Cricket and I like to watch movies genres like Anime and Sci-Fi", stream=True)
    print("\n")
    agent.print_response("what are my favorite movies genres?", stream=True)

if __name__ == "__main__":
    main()
