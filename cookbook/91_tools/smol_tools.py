"""Run Agno agent code inside local or cloud Smol microVMs.

Install ``agno[smol,openai]``; set OPENAI_API_KEY for the agent's model.
Local VMs need supported virtualization; cloud VMs use ``smol cloud login`` or
SMOL_CLOUD_TOKEN. Set SMOL_TARGET=cloud to use managed capacity.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.smol import SmolTools

# One toolkit means one VM shared across the agent's shell, Python, and file
# tools; the same agent code runs locally or in Smol Cloud.
sandbox = SmolTools(target=os.getenv("SMOL_TARGET", "local"))
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[sandbox],
    instructions="Use the Smol VM tools to run code and verify results before answering.",
)

if __name__ == "__main__":
    try:
        agent.print_response(
            "Calculate 6 * 7 in the VM, save it to answer.txt, read the file back, and report its contents."
        )
    finally:
        sandbox.close()
