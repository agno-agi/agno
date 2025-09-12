from agno.agent import Agent
from agno.tools.jina import JinaReaderTools

agent = Agent(tools=[JinaReaderTools()])
agent.print_response("Summarize: https://github.com/agno-agi/agno")
