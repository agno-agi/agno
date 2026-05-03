import dspy
from agno.agents.dspy import DSPyAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

dspy.configure(lm=dspy.LM("openai/gpt-5.4"))

agent = DSPyAgent(
    name="DSPy Assistant",
    program=dspy.ChainOfThought("question -> answer"),
)

agent_os = AgentOS(
    agents=[agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()
