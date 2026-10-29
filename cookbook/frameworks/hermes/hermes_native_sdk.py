"""Compare Hermes's native API with hermes_basic.py in the same environment."""

from os import getenv

from run_agent import AIAgent

agent = AIAgent(
    model=getenv("HERMES_MODEL", ""),
    enabled_toolsets=[],
    quiet_mode=True,
    skip_context_files=True,
    skip_memory=True,
    skip_background_review=True,
    max_iterations=10,
)

if __name__ == "__main__":
    try:
        result = agent.run_conversation("Explain what an AI agent is in two sentences.")
        if (
            result.get("failed")
            or result.get("error")
            or result.get("completed") is False
        ):
            raise RuntimeError(
                result.get("error")
                or result.get("turn_exit_reason")
                or "Hermes did not complete"
            )
        print(result["final_response"])
    finally:
        agent.close()
