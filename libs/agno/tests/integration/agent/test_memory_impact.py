import gc
import tracemalloc
from typing import List, Tuple

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat


class MemoryMonitor:
    """Utility class to monitor memory usage during agent operations using tracemalloc."""

    def __init__(self):
        self.memory_readings: List[Tuple[int, float]] = []
        self.tracemalloc_snapshots: List[tracemalloc.Snapshot] = []
        self.baseline_memory = 0.0

    def start_monitoring(self):
        """Start memory monitoring."""
        tracemalloc.start()
        self._take_reading("start")

    def stop_monitoring(self):
        """Stop memory monitoring."""
        self._take_reading("stop")
        tracemalloc.stop()

    def _take_reading(self, label: str):
        """Take a memory reading using tracemalloc."""
        # Get current memory usage from tracemalloc
        current, peak = tracemalloc.get_traced_memory()
        current_memory_mb = current / 1024 / 1024  # Convert to MB
        peak_memory_mb = peak / 1024 / 1024  # Convert to MB

        # Get tracemalloc snapshot
        current_snapshot = tracemalloc.take_snapshot()

        self.memory_readings.append((len(self.memory_readings), current_memory_mb))
        self.tracemalloc_snapshots.append(current_snapshot)

        print(f"Memory reading {label}: {current_memory_mb:.2f} MB (peak: {peak_memory_mb:.2f} MB)")

    def take_reading(self, label: str = ""):
        """Take a memory reading with optional label."""
        self._take_reading(label)

    def force_gc(self):
        """Force garbage collection and take a reading."""
        gc.collect()
        self._take_reading("after_gc")

    def get_memory_growth(self) -> List[float]:
        """Calculate memory growth between readings."""
        if len(self.memory_readings) < 2:
            return []

        growth = []
        for i in range(1, len(self.memory_readings)):
            prev_memory = self.memory_readings[i - 1][1]
            curr_memory = self.memory_readings[i][1]
            growth.append(curr_memory - prev_memory)
        return growth

    def get_peak_memory(self) -> float:
        """Get peak memory usage."""
        if not self.memory_readings:
            return 0.0
        return max(reading[1] for reading in self.memory_readings)

    def get_final_memory(self) -> float:
        """Get final memory usage."""
        if not self.memory_readings:
            return 0.0
        return self.memory_readings[-1][1]

    def analyze_tracemalloc(self) -> dict:
        """Analyze tracemalloc snapshots for memory leaks."""
        if len(self.tracemalloc_snapshots) < 2:
            return {}

        first_snapshot = self.tracemalloc_snapshots[0]
        last_snapshot = self.tracemalloc_snapshots[-1]

        # Compare snapshots
        stats = last_snapshot.compare_to(first_snapshot, "lineno")

        # Get top memory allocations
        top_stats = stats[:10]

        return {
            "top_allocations": [
                {"file": stat.traceback.format()[-1], "size_diff": stat.size_diff, "count_diff": stat.count_diff}
                for stat in top_stats
            ]
        }


def test_agent_memory_impact_with_gc_monitoring(shared_db):
    """
    Test that creates an agent with memory and storage, runs a series of prompts,
    and monitors memory usage to verify garbage collection is working correctly.
    """
    # Create agent with memory and storage
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        update_memory_on_run=True,
    )

    # Initialize memory monitor
    monitor = MemoryMonitor()
    monitor.start_monitoring()

    session_id = "memory_test_session"
    user_id = "test_user"

    # Series of prompts to test memory usage
    prompts = [
        "Hello, my name is Alice and I like programming.",
        "I work as a software engineer at a tech company.",
        "My favorite programming language is Python.",
        "I enjoy reading science fiction books in my free time.",
        "I have a cat named Whiskers who is very playful.",
        "I'm planning to learn machine learning this year.",
        "What do you remember about me?",
        "Can you summarize our conversation so far?",
        "Tell me something interesting about Python programming.",
        "What are the best practices for memory management in Python?",
    ]

    try:
        # Run each prompt and monitor memory
        for i, prompt in enumerate(prompts):
            print(f"\n--- Running prompt {i + 1}/{len(prompts)} ---")
            monitor.take_reading(f"before_prompt_{i + 1}")

            # Run the agent
            response = agent.run(prompt, session_id=session_id, user_id=user_id)

            assert response is not None
            assert response.content is not None

            monitor.take_reading(f"after_prompt_{i + 1}")

            # Force garbage collection every few prompts to test GC effectiveness
            if (i + 1) % 3 == 0:
                print(f"--- Forcing garbage collection after prompt {i + 1} ---")
                monitor.force_gc()

        # Final memory analysis
        monitor.take_reading("final")

        # Get memory statistics
        memory_growth = monitor.get_memory_growth()
        peak_memory = monitor.get_peak_memory()
        final_memory = monitor.get_final_memory()
        monitor.analyze_tracemalloc()

        print("\n=== Memory Analysis ===")
        print(f"Peak memory usage: {peak_memory:.2f} MB")
        print(f"Final memory usage: {final_memory:.2f} MB")
        print(f"Number of memory readings: {len(monitor.memory_readings)}")

        if memory_growth:
            print(f"Average memory growth per operation: {sum(memory_growth) / len(memory_growth):.2f} MB")
            print(f"Max memory growth in single operation: {max(memory_growth):.2f} MB")

        # Verify that memory usage is reasonable - the agent should not utilize excessive memory
        assert final_memory < 1000, f"Final memory usage too high: {final_memory:.2f} MB"

        # Verify that garbage collection is working
        # After GC, memory should not be significantly higher than before
        gc_readings = [i for i, (_, memory) in enumerate(monitor.memory_readings) if "after_gc" in str(i)]
        if len(gc_readings) > 1:
            # Check that memory after GC is not growing excessively
            for i in range(1, len(gc_readings)):
                prev_gc_memory = monitor.memory_readings[gc_readings[i - 1]][1]
                curr_gc_memory = monitor.memory_readings[gc_readings[i]][1]
                memory_increase = curr_gc_memory - prev_gc_memory

                # Allow some memory growth but not excessive
                assert memory_increase < 1, f"Memory leak detected: {memory_increase:.2f} MB increase after GC"

        # Verify that the agent's memory and storage are working correctly
        # Check that memories were created
        user_memories = shared_db.get_user_memories(user_id=user_id)
        assert len(user_memories) > 0, "No user memories were created"

        # Check that sessions were stored
        session_from_storage = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        assert session_from_storage is not None, "Session was not stored"

        # Check that runs are in memory
        assert session_from_storage.runs[0].session_id == session_id, "Session runs not found in memory"
        assert len(session_from_storage.runs) == len(prompts), (
            f"Expected {len(prompts)} runs, got {len(session_from_storage.runs[session_id])}"
        )

        print("✅ Memory impact test completed successfully")
        print(f"✅ Created {len(user_memories)} user memories")
        print(f"✅ Stored {len(session_from_storage.runs)} runs in memory")

    finally:
        monitor.stop_monitoring()


def test_agent_memory_cleanup_after_session_switch(shared_db):
    """
    Test that verifies memory is properly cleaned up when switching between sessions.
    """
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        update_memory_on_run=True,
    )

    monitor = MemoryMonitor()
    monitor.start_monitoring()

    user_id = "test_user_cleanup"

    try:
        # Create multiple sessions and run prompts
        sessions = ["session_1", "session_2", "session_3"]

        for session_idx, session_id in enumerate(sessions):
            print(f"\n--- Testing session {session_id} ---")
            monitor.take_reading(f"before_session_{session_idx + 1}")

            # Run a few prompts in this session
            for prompt_idx in range(3):
                prompt = f"This is prompt {prompt_idx + 1} in session {session_id}"
                response = agent.run(prompt, session_id=session_id, user_id=user_id)

                assert response is not None
                assert response.content is not None

            monitor.take_reading(f"after_session_{session_idx + 1}")

            # Force GC after each session
            monitor.force_gc()

        # Switch back to first session and verify memory doesn't grow excessively
        print("\n--- Switching back to first session ---")
        monitor.take_reading("before_switch_back")

        response = agent.run(
            "What do you remember from our previous conversation?", session_id=sessions[0], user_id=user_id
        )

        assert response is not None
        monitor.take_reading("after_switch_back")
        monitor.force_gc()

        # Verify memory usage is reasonable
        final_memory = monitor.get_final_memory()
        assert final_memory < 1000, f"Final memory usage too high: {final_memory:.2f} MB"

        # Verify all sessions are properly stored
        for session_id in sessions:
            session_from_storage = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
            assert session_from_storage is not None, f"Session {session_id} was not stored"
            assert session_from_storage.runs[0].session_id == session_id, (
                f"Session {session_id} runs not found in memory"
            )

        print("✅ Session switching memory test completed successfully")

    finally:
        monitor.stop_monitoring()
