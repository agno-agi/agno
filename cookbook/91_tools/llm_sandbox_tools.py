"""
LLM Sandbox Tools Example - self-hosted sandboxed code execution.

Unlike the E2B and Daytona toolkits, this runs on container infrastructure you
already operate. There is no API key, no per-execution cost, and code never
leaves your machines -- which matters under data-governance constraints, for
air-gapped evaluation, and for batch work where per-call pricing dominates.

Prerequisites:

1. A container runtime. Docker by default; Podman and Kubernetes also work.

2. Install required packages:
   uv pip install "llm-sandbox[docker]"

No environment variables and no account are required.

Security:
- The container is hardened by default: no network, capped memory and pids,
  every Linux capability dropped except DAC_OVERRIDE, no-new-privileges set.
- DAC_OVERRIDE is kept deliberately: llm-sandbox copies the source file into
  the container and cannot read it otherwise.
- This is container isolation, not VM isolation. For deliberately adversarial
  code, pair it with a hardened runtime such as gVisor or Kata Containers.
"""

from agno.agent import Agent
from agno.tools.llm_sandbox import LLMSandboxTools

agent = Agent(
    tools=[LLMSandboxTools()],
    instructions="You solve problems by writing and running code. Always print the result.",
    markdown=True,
)

agent.print_response("What is the standard deviation of the first 50 prime numbers?")

# Another language:
#   Agent(tools=[LLMSandboxTools(lang="ruby")])
#
# Another backend:
#   Agent(tools=[LLMSandboxTools(backend="kubernetes")])
#
# Pre-baked dependencies, since the default network isolation blocks installs:
#   Agent(tools=[LLMSandboxTools(image="my-registry/python-with-pandas:1.0")])
