"""
Example demonstrating a custom cancellation manager.

Shows how to extend BaseRunCancellationManager to implement your own
cancellation backend (e.g., a database, a message queue, an API, etc.).

This example creates a file-based cancellation manager that persists
cancellation state to a JSON file, which could be shared across processes
via a network filesystem.

Usage:
    .venvs/demo/bin/python cookbook/02_agents/other/custom_cancellation_manager.py
"""

import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict

from agno.agent import Agent
from agno.exceptions import RunCancelledException
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent
from agno.run.cancel import set_cancellation_manager
from agno.run.cancellation_management.base import BaseRunCancellationManager

# ---------------------------------------------------------------------------
# Create Custom Cancellation Manager
# ---------------------------------------------------------------------------


class FileBasedCancellationManager(BaseRunCancellationManager):
    """A cancellation manager that persists state to a JSON file.

    This is a simple example showing how to build a custom backend.
    In production, you might use a database, Redis, or an API instead.
    """

    def __init__(self, file_path: str):
        self._file_path = Path(file_path)
        self._lock = threading.Lock()
        # Initialize file if it doesn't exist
        if not self._file_path.exists():
            self._write_state({})

    def _read_state(self) -> Dict[str, bool]:
        """Read the cancellation state from the file."""
        try:
            return json.loads(self._file_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_state(self, state: Dict[str, bool]) -> None:
        """Write the cancellation state to the file."""
        self._file_path.write_text(json.dumps(state, indent=2))

    def register_run(self, run_id: str) -> None:
        with self._lock:
            state = self._read_state()
            # Use setdefault to preserve cancel-before-start intent
            state.setdefault(run_id, False)
            self._write_state(state)

    async def aregister_run(self, run_id: str) -> None:
        self.register_run(run_id)

    def cancel_run(self, run_id: str) -> bool:
        with self._lock:
            state = self._read_state()
            was_registered = run_id in state
            state[run_id] = True
            self._write_state(state)
            return was_registered

    async def acancel_run(self, run_id: str) -> bool:
        return self.cancel_run(run_id)

    def is_cancelled(self, run_id: str) -> bool:
        state = self._read_state()
        return state.get(run_id, False)

    async def ais_cancelled(self, run_id: str) -> bool:
        return self.is_cancelled(run_id)

    def cleanup_run(self, run_id: str) -> None:
        with self._lock:
            state = self._read_state()
            state.pop(run_id, None)
            self._write_state(state)

    async def acleanup_run(self, run_id: str) -> None:
        self.cleanup_run(run_id)

    def raise_if_cancelled(self, run_id: str) -> None:
        if self.is_cancelled(run_id):
            raise RunCancelledException(f"Run {run_id} was cancelled")

    async def araise_if_cancelled(self, run_id: str) -> None:
        self.raise_if_cancelled(run_id)

    def get_active_runs(self) -> Dict[str, bool]:
        return self._read_state()

    async def aget_active_runs(self) -> Dict[str, bool]:
        return self.get_active_runs()


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------


def main():
    """Demonstrate the custom file-based cancellation manager."""

    # Create a temporary file for cancellation state
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        state_file = f.name
        f.write("{}")

    print(f"Cancellation state file: {state_file}")
    print("=" * 50)

    # Set up the custom cancellation manager
    manager = FileBasedCancellationManager(file_path=state_file)
    set_cancellation_manager(manager)
    print("Custom file-based cancellation manager configured\n")

    # Create an agent
    agent = Agent(
        name="StoryAgent",
        model=OpenAIResponses(id="gpt-5-mini"),
        description="An agent that writes stories",
    )

    # Container for sharing state between threads
    run_id_container: dict = {}

    def run_agent():
        content_pieces = []
        for chunk in agent.run(
            "Write a long story about a wizard learning Python programming. "
            "Make it detailed with lots of dialogue.",
            stream=True,
        ):
            if "run_id" not in run_id_container and chunk.run_id:
                run_id_container["run_id"] = chunk.run_id

            if chunk.event == RunEvent.run_content:
                print(chunk.content, end="", flush=True)
                content_pieces.append(chunk.content)
            elif chunk.event == RunEvent.run_cancelled:
                print(f"\n\n[CANCELLED] Run was cancelled: {chunk.run_id}")
                run_id_container["cancelled"] = True
                return

        run_id_container["cancelled"] = False

    def cancel_after_delay():
        time.sleep(5)
        run_id = run_id_container.get("run_id")
        if run_id:
            print(f"\n\n[CANCEL] Cancelling run {run_id} via file-based manager...")

            # Show the state file before cancellation
            state = manager.get_active_runs()
            print(f"[STATE] Before cancel: {state}")

            agent.cancel_run(run_id)

            # Show the state file after cancellation
            state = manager.get_active_runs()
            print(f"[STATE] After cancel: {state}")

    # Start both threads
    agent_thread = threading.Thread(target=run_agent)
    cancel_thread = threading.Thread(target=cancel_after_delay)

    agent_thread.start()
    cancel_thread.start()

    agent_thread.join()
    cancel_thread.join()

    # Final state
    print("\n" + "=" * 50)
    print("RESULTS:")
    print(f"  Was cancelled: {run_id_container.get('cancelled', 'unknown')}")
    print(f"  Final state file contents: {manager.get_active_runs()}")

    # Cleanup
    Path(state_file).unlink(missing_ok=True)
    print("\nExample completed!")


if __name__ == "__main__":
    main()
