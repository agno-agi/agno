from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIChat
from agno.utils.pprint import pprint_run_response

try:
    from mem0 import MemoryClient
except ImportError:
    raise ImportError(
        "mem0 is not installed. Please install it using `pip install mem0ai`."
    )

client = MemoryClient()

user_id = "agno"
messages = [
    {"role": "user", "content": "My name is John Billings."},
    {"role": "user", "content": "I live in NYC."},
    {"role": "user", "content": "I'm going to a concert tomorrow."},
]
# Comment out the following line after running the script once
client.add(messages, user_id=user_id)

agent = Agent(
    model=OpenAIChat(),
    dependencies={"memory": client.get_all(user_id=user_id)},
    add_dependencies_to_context=True,
)
run: RunOutput = agent.run("What do you know about me?")

pprint_run_response(run)

input = [{"role": i.role, "content": str(i.content)} for i in (run.messages or [])]
client.add(messages, user_id=user_id)
