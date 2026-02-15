"""
Cancel Run
=============================

Demonstrates cancelling an in-flight team run from a separate thread.
"""

import threading
import time

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent
from agno.run.base import RunStatus
from agno.run.team import TeamRunEvent
from agno.team import Team


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def long_running_task(team: Team, run_id_container: dict) -> None:
    """Run a long team task that can be cancelled."""
    try:
        final_response = None
        content_pieces = []

        for chunk in team.run(
            "Write a very long story about a dragon who learns to code. "
            "Make it at least 2000 words with detailed descriptions and dialogue. "
            "Take your time and be very thorough.",
            stream=True,
        ):
            if "run_id" not in run_id_container and chunk.run_id:
                print(f"Team run started: {chunk.run_id}")
                run_id_container["run_id"] = chunk.run_id

            if chunk.event in [TeamRunEvent.run_content, RunEvent.run_content]:
                print(chunk.content, end="", flush=True)
                content_pieces.append(chunk.content)
            elif chunk.event == RunEvent.run_cancelled:
                print(f"\nMember run was cancelled: {chunk.run_id}")
                run_id_container["result"] = {
                    "status": "cancelled",
                    "run_id": chunk.run_id,
                    "cancelled": True,
                    "content": "".join(content_pieces)[:200] + "..."
                    if content_pieces
                    else "No content before cancellation",
                }
                return
            elif chunk.event == TeamRunEvent.run_cancelled:
                print(f"\nTeam run was cancelled: {chunk.run_id}")
                run_id_container["result"] = {
                    "status": "cancelled",
                    "run_id": chunk.run_id,
                    "cancelled": True,
                    "content": "".join(content_pieces)[:200] + "..."
                    if content_pieces
                    else "No content before cancellation",
                }
                return
            elif hasattr(chunk, "status") and chunk.status == RunStatus.completed:
                final_response = chunk

        if final_response:
            run_id_container["result"] = {
                "status": final_response.status.value
                if final_response.status
                else "completed",
                "run_id": final_response.run_id,
                "cancelled": final_response.status == RunStatus.cancelled,
                "content": ("".join(content_pieces)[:200] + "...")
                if content_pieces
                else "No content",
            }
        else:
            run_id_container["result"] = {
                "status": "unknown",
                "run_id": run_id_container.get("run_id"),
                "cancelled": False,
                "content": ("".join(content_pieces)[:200] + "...")
                if content_pieces
                else "No content",
            }

    except Exception as e:
        print(f"\nException in run: {str(e)}")
        run_id_container["result"] = {
            "status": "error",
            "error": str(e),
            "run_id": run_id_container.get("run_id"),
            "cancelled": True,
            "content": "Error occurred",
        }


def cancel_after_delay(
    team: Team, run_id_container: dict, delay_seconds: int = 3
) -> None:
    """Cancel the team run after a specified delay."""
    print(f"Will cancel team run in {delay_seconds} seconds...")
    time.sleep(delay_seconds)

    run_id = run_id_container.get("run_id")
    if run_id:
        print(f"Cancelling team run: {run_id}")
        success = team.cancel_run(run_id)
        if success:
            print(f"Team run {run_id} marked for cancellation")
        else:
            print(
                f"Failed to cancel team run {run_id} (may not exist or already completed)"
            )
    else:
        print("No run_id found to cancel")


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
storyteller_agent = Agent(
    name="StorytellerAgent",
    model=OpenAIResponses(id="gpt-5-mini"),
    description="An agent that writes creative stories",
)

editor_agent = Agent(
    name="EditorAgent",
    model=OpenAIResponses(id="gpt-5-mini"),
    description="An agent that reviews and improves stories",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Storytelling Team",
    members=[storyteller_agent, editor_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    description="A team that collaborates to write detailed stories",
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
def main() -> None:
    print("Starting team run cancellation example...")
    print("=" * 50)

    run_id_container = {}

    team_thread = threading.Thread(
        target=lambda: long_running_task(team, run_id_container), name="TeamRunThread"
    )

    cancel_thread = threading.Thread(
        target=cancel_after_delay,
        args=(team, run_id_container, 8),
        name="CancelThread",
    )

    print("Starting team run thread...")
    team_thread.start()

    print("Starting cancellation thread...")
    cancel_thread.start()

    print("Waiting for threads to complete...")
    team_thread.join()
    cancel_thread.join()

    print("\n" + "=" * 50)
    print("RESULTS:")
    print("=" * 50)

    result = run_id_container.get("result")
    if result:
        print(f"Status: {result['status']}")
        print(f"Run ID: {result['run_id']}")
        print(f"Was Cancelled: {result['cancelled']}")

        if result.get("error"):
            print(f"Error: {result['error']}")
        else:
            print(f"Content Preview: {result['content']}")

        if result["cancelled"]:
            print("\nSUCCESS: Team run was successfully cancelled!")
        else:
            print("\nWARNING: Team run completed before cancellation")
    else:
        print("No result obtained - check if cancellation happened during streaming")

    print("\nTeam cancellation example completed!")


if __name__ == "__main__":
    main()
