"""
Preference Survival Test

Tests if user preferences stated early in conversation survive compaction.
This is a critical test - compaction should preserve user intent.

Run: .venvs/demo/bin/python cookbook/14_context_compaction/06_preference_survival.py
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/preference_survival_test.db")

# Create compaction manager with aggressive settings to force compaction
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),
    compact_context=True,
    compact_context_message_limit=4,
    compact_context_keep_recent=2,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-mini"),
    session_id="preference-survival-test",
    db=db,
    add_history_to_context=True,
    compaction_manager=compaction_manager,
    markdown=True,
)

print("Preference Survival Test")
print("=" * 60)
print()

# Turn 1: State preferences clearly
preferences = """
IMPORTANT - Remember these preferences for our entire conversation:
- My name is Marcus and I'm a backend engineer
- I prefer Python with type hints everywhere
- I use pytest for testing, NOT unittest
- I prefer composition over inheritance
- Always use dataclasses, not regular classes
- Logging with structlog, not print statements
- I hate abbreviations - use full variable names
"""

print("Turn 1: Setting preferences...")
response = agent.run(preferences)
print(f"Response: {response.content[:100]}...")

# Turn 2-4: Generate content to push toward compaction
filler_prompts = [
    "Explain the singleton pattern with a detailed Python example including all the edge cases.",
    "Now explain the factory pattern with multiple examples of when to use abstract factories vs simple factories.",
    "Describe the observer pattern with a complete implementation including async support.",
]

for i, prompt in enumerate(filler_prompts, 2):
    print(f"\nTurn {i}: {prompt[:50]}...")
    response = agent.run(prompt)

    # Check if compaction happened
    state = response.compaction_state
    if state and state.total_compactions > 0:
        print(
            f"  [COMPACTION #{state.total_compactions}] {state.total_tokens_saved} tokens saved"
        )

# Turn 5: Test if preferences survived
print("\n" + "=" * 60)
print("VERIFICATION: Testing if preferences survived compaction")
print("=" * 60)

test_prompt = """
Create a simple logging utility class for me.
What's my name again, and what testing framework should you use?
"""

print(f"\nTest prompt: {test_prompt.strip()}")
response = agent.run(test_prompt)
print(f"\nResponse:\n{response.content}")

# Analyze response for preference violations
print("\n" + "=" * 60)
print("ANALYSIS")
print("=" * 60)

response_lower = response.content.lower()

checks = [
    ("Name Marcus remembered", "marcus" in response_lower),
    (
        "Uses pytest (not unittest)",
        "pytest" in response_lower or "unittest" not in response_lower,
    ),
    (
        "Uses structlog (not print)",
        "structlog" in response_lower or "print(" not in response.content,
    ),
    (
        "Uses dataclass",
        "dataclass" in response_lower or "@dataclass" in response.content,
    ),
    (
        "Type hints present",
        ": str" in response.content
        or ": int" in response.content
        or "-> " in response.content,
    ),
]

passed = 0
for check_name, check_result in checks:
    status = "PASS" if check_result else "FAIL"
    print(f"  {status}: {check_name}")
    if check_result:
        passed += 1

print(f"\nScore: {passed}/{len(checks)} preferences preserved")

# Show compaction state from the last response
state = response.compaction_state
if state and state.summary:
    print("\nCompaction summary preview:")
    print("-" * 40)
    print(state.summary[:800] if state.summary else "(no summary)")
