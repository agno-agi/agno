"""Configure the shared external-agent retry policy for Prime CLI failures.

Retries can repeat native tool side effects; choose a prompt appropriate for that.
"""

from os import getenv

from agno.agents.prime import PrimeAgent

agent = PrimeAgent(
    name="Prime Retry Demo",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    retries=1,
    delay_between_retries=2,
    exponential_backoff=True,
    timeout=120,
    ephemeral=True,
)

if __name__ == "__main__":
    agent.print_response("Reply with exactly OK. Do not modify files.", stream=True)
