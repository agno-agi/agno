from agno.agent import Agent
from agno.tools.sleep import SleepTools

# Example 1: Enable specific sleep functions
agent = Agent(tools=[SleepTools(enable_sleep=True)], name="Sleep Agent")

# Example 2: Enable all sleep functions
agent_all = Agent(tools=[SleepTools(all=True)], name="Full Sleep Agent")

# Test the agents
agent.print_response("Sleep for 2 seconds")
agent_all.print_response("Sleep for 5 seconds")
