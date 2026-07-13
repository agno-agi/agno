"""
Cancel Run
==========

Demonstrates starting a workflow run in one thread and cancelling it from another.
"""

import threading
import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunEvent
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunEvent
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


# ---------------------------------------------------------------------------
# Define Helpers
# ---------------------------------------------------------------------------
def long_running_task(workflow: Workflow, run_id_container: dict) -> None:
    try:
        final_response = None
        content_pieces = []

        for chunk in workflow.run(
            "Write a very long story about a dragon who learns to code. "
            "Make it at least 2000 words with detailed descriptions and dialogue. "
            "Take your time and be very thorough.",
            stream=True,
        ):
            if "run_id" not in run_id_container and chunk.run_id:
                print(f"[START] Workflow run started: {chunk.run_id}")
                run_id_container["run_id"] = chunk.run_id

            if chunk.event in [RunEvent.run_content]:
                print(chunk.content, end="", flush=True)
                content_pieces.append(chunk.content)
            elif chunk.event == RunEvent.run_cancelled:
                print(f"\n[CANCELLED] Workflow run was cancelled: {chunk.run_id}")
                run_id_container["result"] = {
                    "status": "cancelled",
                    "run_id": chunk.run_id,
                    "cancelled": True,
                    "content": "".join(content_pieces)[:200] + "..."
                    if content_pieces
                    else "No content before cancellation",
                }
                return
            elif chunk.event == WorkflowRunEvent.workflow_cancelled:
                print(f"\n[CANCELLED] Workflow run was cancelled: {chunk.run_id}")
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
        print(f"\n[ERROR] Exception in run: {str(e)}")
        run_id_container["result"] = {
            "status": "error",
            "error": str(e),
            "run_id": run_id_container.get("run_id"),
            "cancelled": True,
            "content": "Error occurred",
        }


def cancel_after_delay(
    workflow: Workflow, run_id_container: dict, delay_seconds: int = 3
) -> None:
    print(f"[WAIT] Will cancel workflow run in {delay_seconds} seconds...")
    time.sleep(delay_seconds)

    run_id = run_id_container.get("run_id")
    if run_id:
        print(f"[CANCEL] Cancelling workflow run: {run_id}")
        success = workflow.cancel_run(run_id)
        if success:
            print(f"[OK] Workflow run {run_id} marked for cancellation")
        else:
            print(
                f"[ERROR] Failed to cancel workflow run {run_id} (may not exist or already completed)"
            )
    else:
        print("[WARN] No run_id found to cancel")


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
def main() -> None:
    researcher = Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools()],
        instructions="Research the given topic and provide key facts and insights.",
    )

    writer = Agent(
        name="Writing Agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="Write a comprehensive article based on the research provided. Make it engaging and well-structured.",
    )

    research_step = Step(
        name="research",
        agent=researcher,
        description="Research the topic and gather information",
    )

    writing_step = Step(
        name="writing",
        agent=writer,
        description="Write an article based on the research",
    )

    article_workflow = Workflow(
        description="Automated article creation from research to writing",
        steps=[research_step, writing_step],
        debug_mode=True,
    )

    print("[START] Starting workflow run cancellation example...")
    print("=" * 50)

    run_id_container = {}

    workflow_thread = threading.Thread(
        target=lambda: long_running_task(article_workflow, run_id_container),
        name="WorkflowRunThread",
    )

    cancel_thread = threading.Thread(
        target=cancel_after_delay,
        args=(article_workflow, run_id_container, 8),
        name="CancelThread",
    )

    print("[RUN] Starting workflow run thread...")
    workflow_thread.start()

    print("[RUN] Starting cancellation thread...")
    cancel_thread.start()

    print("[WAIT] Waiting for threads to complete...")
    workflow_thread.join()
    cancel_thread.join()

    print("\n" + "=" * 50)
    print("RESULTS")
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
            print("\n[OK] SUCCESS: Workflow run was successfully cancelled")
        else:
            print("\n[WARN] Workflow run completed before cancellation")
    else:
        print(
            "[ERROR] No result obtained - check if cancellation happened during streaming"
        )

    print("\nWorkflow cancellation example completed")


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
