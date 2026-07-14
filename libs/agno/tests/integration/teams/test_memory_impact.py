import asyncio
import gc
import tracemalloc
from typing import List, Tuple

import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


class MemoryMonitor:
    """Utility class to monitor memory usage during team operations using tracemalloc."""

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


def test_team_memory_impact_with_gc_monitoring(shared_db):
    """
    Test that creates a team with memory and storage, runs a series of prompts,
    and monitors memory usage to verify garbage collection is working correctly.
    """

    # Create simple agents for the team
    def simple_calculator(operation: str, a: float, b: float) -> str:
        """Simple calculator function."""
        if operation == "add":
            return f"{a} + {b} = {a + b}"
        elif operation == "subtract":
            return f"{a} - {b} = {a - b}"
        elif operation == "multiply":
            return f"{a} * {b} = {a * b}"
        elif operation == "divide":
            return f"{a} / {b} = {a / b}"
        else:
            return f"Unknown operation: {operation}"

    def text_processor(text: str, operation: str) -> str:
        """Simple text processing function."""
        if operation == "uppercase":
            return text.upper()
        elif operation == "lowercase":
            return text.lower()
        elif operation == "length":
            return f"Length: {len(text)} characters"
        else:
            return f"Unknown operation: {operation}"

    # Create team members
    calculator_agent = Agent(
        name="Calculator Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Perform mathematical calculations",
        tools=[simple_calculator],
        db=shared_db,
        update_memory_on_run=True,
    )

    text_agent = Agent(
        name="Text Processor Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Process and analyze text",
        tools=[text_processor],
        db=shared_db,
        update_memory_on_run=True,
    )

    # Create team with memory and storage
    team = Team(
        name="Memory Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[calculator_agent, text_agent],
        respond_directly=True,
        determine_input_for_members=False,
        db=shared_db,
        update_memory_on_run=True,
        instructions="Route mathematical questions to the calculator agent and text processing questions to the text processor agent.",
    )

    # Initialize memory monitor
    monitor = MemoryMonitor()
    monitor.start_monitoring()

    session_id = "team_memory_test_session"
    user_id = "test_user"

    # Series of prompts to test memory usage
    prompts = [
        "Calculate 15 + 27",
        "What is 42 - 18?",
        "Process the text 'Hello World' to uppercase",
        "Calculate 7 * 8",
        "What is the length of 'Python Programming'?",
        "Calculate 100 / 4",
        "Convert 'MEMORY TEST' to lowercase",
        "What is 3 + 5 + 7?",
        "Process 'Team Memory Impact Test' to uppercase",
        "Calculate 25 * 4",
    ]

    try:
        # Run each prompt and monitor memory
        for i, prompt in enumerate(prompts):
            print(f"\n--- Running team prompt {i + 1}/{len(prompts)} ---")
            monitor.take_reading(f"before_prompt_{i + 1}")

            # Run the team
            response = team.run(prompt, session_id=session_id, user_id=user_id)

            assert response is not None
            assert response.content is not None
            assert response.run_id is not None

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

        print("\n=== Team Memory Analysis ===")
        print(f"Peak memory usage: {peak_memory:.2f} MB")
        print(f"Final memory usage: {final_memory:.2f} MB")
        print(f"Number of memory readings: {len(monitor.memory_readings)}")

        if memory_growth:
            print(f"Average memory growth per operation: {sum(memory_growth) / len(memory_growth):.2f} MB")
            print(f"Max memory growth in single operation: {max(memory_growth):.2f} MB")

        # STRICT MEMORY LIMITS: Final memory must be under 20MB
        assert final_memory < 20, f"Final memory usage too high: {final_memory:.2f} MB (limit: 20MB)"

        # Verify that garbage collection is working
        # After GC, memory should not be significantly higher than before
        gc_readings = [i for i, (_, memory) in enumerate(monitor.memory_readings) if "after_gc" in str(i)]
        if len(gc_readings) > 1:
            # Check that memory after GC is not growing excessively
            for i in range(1, len(gc_readings)):
                prev_gc_memory = monitor.memory_readings[gc_readings[i - 1]][1]
                curr_gc_memory = monitor.memory_readings[gc_readings[i]][1]
                memory_increase = curr_gc_memory - prev_gc_memory

                # Allow minimal memory growth but not excessive
                assert memory_increase < 0.5, f"Memory leak detected: {memory_increase:.2f} MB increase after GC"

        # Check that sessions were stored
        session_from_storage = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
        assert session_from_storage is not None, "Session was not stored"

        # Check that runs are in memory
        assert len(session_from_storage.runs) > len(prompts)
    finally:
        monitor.stop_monitoring()


def test_team_memory_cleanup_after_session_switch(shared_db):
    """
    Test that verifies team memory is properly cleaned up when switching between sessions.
    """

    # Create simple team with basic agents
    def simple_function(input_text: str) -> str:
        return f"Processed: {input_text}"

    agent = Agent(
        name="Simple Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Process simple requests",
        tools=[simple_function],
        db=shared_db,
        update_memory_on_run=True,
    )

    team = Team(
        name="Session Switch Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
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
            print(f"\n--- Testing team session {session_id} ---")
            monitor.take_reading(f"before_session_{session_idx + 1}")

            # Run a few prompts in this session
            for prompt_idx in range(3):
                prompt = f"Process this text: session {session_id} prompt {prompt_idx + 1}"
                response = team.run(prompt, session_id=session_id, user_id=user_id)

                assert response is not None
                assert response.content is not None

            monitor.take_reading(f"after_session_{session_idx + 1}")

            # Force GC after each session
            monitor.force_gc()

        # Switch back to first session and verify memory doesn't grow excessively
        print("\n--- Switching back to first session ---")
        monitor.take_reading("before_switch_back")

        response = team.run(
            "What do you remember from our previous conversation?", session_id=sessions[0], user_id=user_id
        )

        assert response is not None
        monitor.take_reading("after_switch_back")
        monitor.force_gc()

        # STRICT MEMORY LIMITS: Final memory must be under 20MB
        final_memory = monitor.get_final_memory()
        assert final_memory < 5, f"Final memory usage too high: {final_memory:.2f} MB (limit: 5MB)"

        # Verify all sessions are properly stored
        for session_id in sessions:
            session_from_storage = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
            assert session_from_storage is not None, f"Session {session_id} was not stored"

    finally:
        monitor.stop_monitoring()


@pytest.mark.asyncio
async def test_team_memory_with_multiple_members(shared_db):
    """
    Test memory usage with multiple team members to ensure scalability.
    """

    # Create multiple agents with realistic functions that would generate memories
    def calculate_budget(income: float, expenses: float, savings_goal: float) -> str:
        """Calculate budget and provide financial advice."""
        disposable_income = income - expenses
        months_to_goal = savings_goal / disposable_income if disposable_income > 0 else float("inf")

        if disposable_income <= 0:
            return f"⚠️ Your expenses (${expenses:.2f}) exceed your income (${income:.2f}). Consider reducing expenses or increasing income."
        elif months_to_goal <= 12:
            return f"✅ Great! You can reach your ${savings_goal:.2f} goal in {months_to_goal:.1f} months with ${disposable_income:.2f} disposable income."
        else:
            return f"📊 You'll reach your ${savings_goal:.2f} goal in {months_to_goal:.1f} months. Consider increasing savings or adjusting your goal."

    def analyze_health_data(age: int, weight: float, height: float, activity_level: str) -> str:
        """Analyze health data and provide recommendations."""
        bmi = weight / ((height / 100) ** 2)

        if bmi < 18.5:
            category = "underweight"
            recommendation = "Consider increasing caloric intake with healthy foods."
        elif bmi < 25:
            category = "normal weight"
            recommendation = "Maintain your healthy weight with balanced nutrition and exercise."
        elif bmi < 30:
            category = "overweight"
            recommendation = "Focus on portion control and regular physical activity."
        else:
            category = "obese"
            recommendation = "Consult with a healthcare provider for a personalized weight management plan."

        return f"📊 BMI: {bmi:.1f} ({category}). {recommendation} Activity level: {activity_level}"

    def schedule_meeting(duration_minutes: int, priority: str) -> str:
        """Schedule a meeting and provide coordination details."""
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        emoji = priority_emoji.get(priority, "⚪")

        return f"{emoji} Meeting scheduled: {duration_minutes} minutes ({priority} priority)"

    agent1 = Agent(
        name="Financial Advisor",
        model=OpenAIChat(id="gpt-4o-mini"),  # type: ignore
        role="Provide financial planning and budget analysis",
        tools=[calculate_budget],
        db=shared_db,
        update_memory_on_run=True,
        add_history_to_context=True,
    )

    agent2 = Agent(
        name="Health Coach",
        model=OpenAIChat(id="gpt-4o-mini"),  # type: ignore
        role="Analyze health data and provide wellness recommendations",
        tools=[analyze_health_data],
        db=shared_db,
        update_memory_on_run=True,
        add_history_to_context=True,
    )

    agent3 = Agent(
        name="Meeting Coordinator",
        model=OpenAIChat(id="gpt-4o-mini"),  # type: ignore
        role="Help schedule meetings and coordinate team activities",
        tools=[schedule_meeting],
        db=shared_db,
        update_memory_on_run=True,
        add_history_to_context=True,
    )

    team = Team(
        name="Personal Assistant Team",
        model=OpenAIChat(id="gpt-4o-mini"),  # type: ignore
        members=[agent1, agent2, agent3],
        respond_directly=True,
        determine_input_for_members=False,
        db=shared_db,
        update_memory_on_run=True,
        add_history_to_context=True,
        instructions="Route financial questions to the Financial Advisor, health-related questions to the Health Coach, and meeting/scheduling requests to the Meeting Coordinator. Remember user preferences and past interactions to provide personalized assistance.",
    )

    monitor = MemoryMonitor()
    monitor.start_monitoring()

    users = [f"test_user_{i}" for i in range(10)]
    try:
        # Create realistic prompts that would generate meaningful user memories
        realistic_prompts = [
            "I make $5000 per month and spend $3500 on expenses. I want to save $10000 for a vacation. Can you help me plan this?",
            "I'm 28 years old, weigh 70kg, am 175cm tall, and exercise 3 times per week. How's my health looking?",
            "I need to schedule a team meeting with 4 people for 1 hour. It's a high priority project kickoff.",
            "My expenses went up to $4000 this month due to car repairs. How does this affect my vacation savings goal?",
            "I've been working out more and now exercise 5 times per week. Can you update my health assessment?",
            "I need to schedule a follow-up meeting with the same team from last time, but this time it's medium priority and only 30 minutes.",
            "I got a raise to $6000 per month! How much faster can I reach my vacation savings goal now?",
            "I've lost 3kg since our last conversation. Can you recalculate my health metrics?",
            "The team meeting went well. I need to schedule a presentation meeting with 8 stakeholders for 2 hours, high priority.",
            "I'm thinking of buying a house and need to save $50000 for a down payment. How long will this take with my current budget?",
        ]

        print("--- Running realistic multi-member team test (concurrent) ---")

        async def run_prompt(i, prompt):
            response = await team.arun(prompt, session_id=f"{users[i]}_session", user_id=users[i])
            assert response is not None
            assert response.content is not None
            assert len(response.content) > 10, f"Response too short: {response.content}"
            return response

        for _ in range(10):
            tasks = []
            monitor.take_reading("before_concurrent_prompts")
            for i, prompt in enumerate(realistic_prompts):
                tasks.append(run_prompt(i, prompt))
            await asyncio.gather(*tasks)
            monitor.take_reading("after_concurrent_prompts")

        monitor.force_gc()

        # Comprehensive memory growth analysis
        memory_growth = monitor.get_memory_growth()
        peak_memory = monitor.get_peak_memory()
        final_memory = monitor.get_final_memory()
        initial_memory = monitor.memory_readings[0][1] if monitor.memory_readings else 0.0

        print("\n=== Memory Growth Analysis ===")
        print(f"Initial memory: {initial_memory:.2f} MB")
        print(f"Peak memory: {peak_memory:.2f} MB")
        print(f"Final memory: {final_memory:.2f} MB")
        print(f"Total memory growth: {final_memory - initial_memory:.2f} MB")
        print(f"Peak memory growth: {peak_memory - initial_memory:.2f} MB")

        if memory_growth:
            avg_growth = sum(memory_growth) / len(memory_growth)
            max_growth = max(memory_growth)

            print(f"Average memory growth per operation: {avg_growth:.2f} MB")

        # STRICT MEMORY LIMITS: Final memory must be under 20MB
        assert final_memory < 20, f"Memory usage too high with multiple members: {final_memory:.2f} MB (limit: 20MB)"

        # Verify memory growth patterns are reasonable
        if memory_growth:
            # Check that average growth per operation is reasonable (should be small)
            avg_growth = sum(memory_growth) / len(memory_growth)
            assert avg_growth < 2.0, f"Average memory growth too high: {avg_growth:.2f} MB per operation"

            # Check that no single operation causes excessive memory growth
            assert max_growth < 10.0, f"Single operation memory growth too high: {max_growth:.2f} MB"

            # Verify that garbage collection is effective
            # After GC, memory should not be significantly higher than before
            gc_readings = [i for i, (_, memory) in enumerate(monitor.memory_readings) if "after_gc" in str(i)]
            if len(gc_readings) > 1:
                for i in range(1, len(gc_readings)):
                    prev_gc_memory = monitor.memory_readings[gc_readings[i - 1]][1]
                    curr_gc_memory = monitor.memory_readings[gc_readings[i]][1]
                    memory_increase = curr_gc_memory - prev_gc_memory

                    # Allow minimal memory growth but not excessive
                    assert memory_increase < 0.5, f"Memory leak detected: {memory_increase:.2f} MB increase after GC"

        print("✅ Realistic multi-member team test completed successfully")
        print(f"✅ Processed {len(realistic_prompts)} realistic prompts")
        print(f"✅ Final memory: {final_memory:.2f} MB")

    finally:
        monitor.stop_monitoring()
