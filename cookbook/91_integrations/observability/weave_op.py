"""
This example shows how to use weave to log model calls.

Steps to get started with weave:
1. Install weave: pip install weave
2. Add weave.init('project-name') and weave.op() decorators to your functions
3. Authentication:
 - Go to https://wandb.ai and copy your API key from https://wandb.ai/authorize
 - Enter your API key in terminal when prompted
 Or
 - Export your API key as an environment variable:
    - export WANDB_API_KEY=<your-api-key>
"""

import weave
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True, debug_mode=True)

weave.init("agno")


@weave.op()
def run(content: str):
    return agent.run(content)


run("Share a 2 sentence horror story")
