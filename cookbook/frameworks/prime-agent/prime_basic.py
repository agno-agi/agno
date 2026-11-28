"""Run Prime Agent standalone. Requires an installed, authenticated prime-agent CLI."""

from os import getenv

from agno.agents.prime import PrimeAgent

agent = PrimeAgent(
    name="Prime Coder",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    append_system_prompt="Explain your findings clearly. Ask before modifying files.",
)

if __name__ == "__main__":
    agent.print_response("Read the README and summarize this project.", stream=True)
