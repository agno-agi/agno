import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from dotenv import load_dotenv
from memori import Memori
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

db_path = os.getenv("DATABASE_PATH", "memori_agno.db")
engine = create_engine(f"sqlite:///{db_path}")
Session = sessionmaker(bind=engine)

model = OpenAIChat(id="gpt-4o-mini")

# Initialize Memori and register with Agno
mem = Memori(conn=Session).agno.register(openai_chat=model)
mem.attribution(entity_id="cookbook-agent", process_id="demo-session")
mem.config.storage.build()

# Setup your Agent
agent = Agent(
    model=model,
    instructions=[
        "You are a helpful assistant.",
        "Remember customer preferences and history from previous conversations.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    print("Customer: I'm a Python developer and I love building web applications")
    response1 = agent.run("I'm a Python developer and I love building web applications")
    print(f"Agent: {response1.content}\n")

    print("Customer: What do you remember about my programming background?")
    response2 = agent.run("What do you remember about my programming background?")
    print(f"Agent: {response2.content}\n")

    print("Customer: I prefer working in the morning hours, around 8-11 AM")
    response3 = agent.run("I prefer working in the morning hours, around 8-11 AM")
    print(f"Agent: {response3.content}\n")

    print("Customer: What were my productivity preferences again?")
    response4 = agent.run("What were my productivity preferences again?")
    print(f"Agent: {response4.content}")
