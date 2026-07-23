"""
Serve agents from another AgentOS through your own AgentOS.

RemoteAgent is a proxy to an agent hosted on a remote AgentOS. The remote AgentOS
must mount the RemoteAccess interface and pass the agent to it; RemoteAgent then calls
the /remote endpoints of that server.

Prerequisites:
1. Start the backing server:
   python cookbook/05_agent_os/remote/server.py

   The server will run on http://localhost:7778

2. Set your OPENAI_API_KEY environment variable

Then run this app and talk to the remote agents on http://localhost:7777:
   curl -X POST -F "message=What is 15 * 23?" -F "stream=false" http://localhost:7777/agents/assistant-agent/runs
"""

from agno.agent import RemoteAgent
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Proxies to agents hosted on the remote AgentOS
remote_assistant = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="assistant-agent",
)

remote_researcher = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="researcher-agent",
)

agent_os = AgentOS(
    id="remote-agent-client",
    description="AgentOS serving agents that live on a remote AgentOS",
    agents=[remote_assistant, remote_researcher],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="01_remote_agent:app", port=7777)
