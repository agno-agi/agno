"""
Simple Query
============
Basic support workflow: ask a question, get a KB-powered answer.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/simple_query.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import create_support_agent

if __name__ == "__main__":
    agent = create_support_agent(
        customer_id="demo@example.com",
        ticket_id="simple_query",
    )
    agent.print_response(
        "When should I escalate a ticket to Tier 2 support?",
        stream=True,
    )
