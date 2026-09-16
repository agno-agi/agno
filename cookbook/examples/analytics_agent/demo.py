"""Ask about the seeded active MRR, then an unsupported cancellation reason."""

from analytics_agent import agent

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is our active MRR, and which accounts contribute to it?")
    agent.print_response("Why did Cedar cancel? Explain any missing information.")
