"""
Creating a custom memory optimization strategy.

This cookbook shows how to create your own memory optimization strategy by
subclassing MemoryOptimizationStrategy. This is useful when you need custom
logic that the built-in "summarize" and "merge" strategies don't provide.

Run: python cookbook/memory/10_custom_memory_strategy.py
"""

from datetime import datetime
from typing import List

from agno.agent import Agent
from agno.db.schemas import UserMemory
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager, MemoryOptimizationStrategy
from agno.models.base import Model
from agno.models.openai import OpenAIChat


# Define a custom strategy that keeps only the N most recent memories
class RecentOnlyStrategy(MemoryOptimizationStrategy):
    """Keep only the N most recent memories."""

    def __init__(self, keep_count: int = 2):
        self.keep_count = keep_count

    def optimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Keep only the most recent N memories."""
        # Sort by updated_at or created_at, most recent first
        sorted_memories = sorted(
            memories,
            key=lambda m: m.updated_at or m.created_at or datetime.min,
            reverse=True,
        )
        # Keep only the specified number
        return sorted_memories[: self.keep_count]

    async def aoptimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Async version: Keep only the most recent N memories."""
        sorted_memories = sorted(
            memories,
            key=lambda m: m.updated_at or m.created_at or datetime.min,
            reverse=True,
        )
        # Keep only the specified number
        return sorted_memories[: self.keep_count]


# Example usage
db_file = "tmp/custom_memory_strategy.db"
db = SqliteDb(db_file=db_file)

user_id = "user3"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    enable_user_memories=True,
)

# Create some memories
print("Creating memories...")
agent.print_response(
    "I'm currently learning machine learning and it's been an incredible journey so far. I started about 6 months ago with the basics - "
    "linear regression, decision trees, and simple classification algorithms. Now I'm diving into more advanced topics like deep learning "
    "and neural networks. I'm using Python with libraries like scikit-learn, TensorFlow, and PyTorch. "
    "The math can be challenging sometimes, especially the calculus and linear algebra, but I'm working through it step by step.",
    user_id=user_id,
)
agent.print_response(
    "I recently completed an excellent online course on neural networks from Coursera. The course covered everything from basic perceptrons "
    "to complex architectures like CNNs and RNNs. The instructor did a great job explaining backpropagation and gradient descent. "
    "I completed all the programming assignments where we built neural networks from scratch and also used TensorFlow. "
    "The final project was building an image classifier that achieved 92% accuracy on the test set. I'm really proud of that accomplishment.",
    user_id=user_id,
)
agent.print_response(
    "My ultimate goal is to build my own AI projects that solve real-world problems. I have several ideas I want to explore - "
    "maybe a recommendation system, a chatbot for customer service, or perhaps something in computer vision. "
    "I'm trying to identify problems where AI can make a real difference and where I have the skills to build something meaningful. "
    "I know I need more experience and practice, but I'm committed to working on personal projects to build my portfolio.",
    user_id=user_id,
)
agent.print_response(
    "I'm particularly interested in natural language processing applications. The recent advances in large language models are fascinating. "
    "I've been experimenting with transformer architectures and trying to understand how attention mechanisms work. "
    "I'd love to work on projects involving text classification, sentiment analysis, or maybe even building conversational AI. "
    "NLP feels like it's at the cutting edge right now and there are so many interesting problems to solve in this space.",
    user_id=user_id,
)

# Check current memories
print("\nBefore optimization:")
memories_before = agent.get_user_memories(user_id=user_id)
print(f"  Memory count: {len(memories_before)}")

# Count tokens before optimization using custom strategy instance
custom_strategy = RecentOnlyStrategy(keep_count=2)
tokens_before = custom_strategy.count_tokens(memories_before)
print(f"  Token count: {tokens_before} tokens")

print("\nAll memories:")
for i, memory in enumerate(memories_before, 1):
    print(f"  {i}. {memory.memory}")

# Use custom strategy to keep only 2 most recent memories
print("\nOptimizing with custom RecentOnlyStrategy (keep_count=2)...")

memory_manager = MemoryManager(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
)

memory_manager.optimize_memories(
    user_id=user_id,
    strategy=custom_strategy,  # Pass custom strategy instance
    apply=True,  # Apply changes to database
)

# Check optimized memories
print("\nAfter optimization:")
memories_after = agent.get_user_memories(user_id=user_id)
print(f"  Memory count: {len(memories_after)}")

# Count tokens after optimization
tokens_after = custom_strategy.count_tokens(memories_after)
print(f"  Token count: {tokens_after} tokens")

# Show what was kept/removed
if tokens_before > 0:
    reduction_pct = ((tokens_before - tokens_after) / tokens_before) * 100
    tokens_saved = tokens_before - tokens_after
    print(
        f"  Reduction: {reduction_pct:.1f}% ({tokens_saved} tokens saved by keeping 2 most recent)"
    )

print("\nRemaining memories (2 most recent):")
for i, memory in enumerate(memories_after, 1):
    print(f"  {i}. {memory.memory}")
