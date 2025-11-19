"""
Memory optimization using the "summarize" strategy.

The "summarize" strategy combines all memories into a single comprehensive summary,
achieving maximum compression. This is useful when you need aggressive token
reduction and can accept losing the individual memory structure.

Run: python cookbook/memory/09_memory_summarize_strategy.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager, SummarizeStrategy
from agno.memory.strategies.types import MemoryOptimizationStrategyType
from agno.models.openai import OpenAIChat

db_file = "tmp/memory_summarize_strategy.db"
db = SqliteDb(db_file=db_file)

user_id = "user2"

# Create agent with memory enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    enable_user_memories=True,
)

# Create some memories for a user
print("Creating memories...")
agent.print_response(
    "I have a wonderful pet dog named Max who is 3 years old. He's a golden retriever and he's such a friendly and energetic dog. "
    "We got him as a puppy when he was just 8 weeks old. He loves playing fetch in the park and going on long walks. "
    "Max is really smart too - he knows about 15 different commands and tricks. Taking care of him has been one of the most "
    "rewarding experiences of my life. He's basically part of the family now.",
    user_id=user_id,
)
agent.print_response(
    "I currently live in San Francisco, which is an amazing city despite all its challenges. I've been here for about 5 years now. "
    "I work in the tech industry as a product manager at a mid-sized software company. The tech scene here is incredible - "
    "there are so many smart people working on interesting problems. The cost of living is definitely high, but the opportunities "
    "and the community make it worthwhile. I live in the Mission district which has great food and a vibrant culture.",
    user_id=user_id,
)
agent.print_response(
    "On weekends, I really enjoy hiking in the beautiful areas around the Bay Area. There are so many amazing trails - "
    "from Mount Tamalpais to Big Basin Redwoods. I usually go hiking with a group of friends and we try to explore new trails every month. "
    "I also love trying new restaurants. San Francisco has such an incredible food scene with cuisines from all over the world. "
    "I'm always on the lookout for hidden gems and new places to try. My favorite types of cuisine are Japanese, Thai, and Mexican.",
    user_id=user_id,
)
agent.print_response(
    "I've been learning to play the piano for about a year and a half now. It's something I always wanted to do but never had time for. "
    "I finally decided to commit to it and I practice almost every day, usually for 30-45 minutes. "
    "I'm working through classical pieces right now - I can play some simple Bach and Mozart compositions. "
    "My goal is to eventually be able to play some jazz piano as well. Having a creative hobby like this has been great for my mental health "
    "and it's nice to have something completely different from my day job.",
    user_id=user_id,
)

# Check current memories
print("\nBefore optimization:")
memories_before = agent.get_user_memories(user_id=user_id)
print(f"  Memory count: {len(memories_before)}")

# Count tokens before optimization
strategy = SummarizeStrategy()
tokens_before = strategy.count_tokens(memories_before)
print(f"  Token count: {tokens_before} tokens")

print("\nIndividual memories:")
for i, memory in enumerate(memories_before, 1):
    print(f"  {i}. {memory.memory}")

# Create memory manager and optimize memories
memory_manager = MemoryManager(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
)

print("\nOptimizing memories with 'summarize' strategy...")
memory_manager.optimize_memories(
    user_id=user_id,
    strategy=MemoryOptimizationStrategyType.SUMMARIZE,  # Combine all memories into one
    apply=True,  # Apply changes to database
)

# Check optimized memories
print("\nAfter optimization:")
memories_after = agent.get_user_memories(user_id=user_id)
print(f"  Memory count: {len(memories_after)}")

# Count tokens after optimization
tokens_after = strategy.count_tokens(memories_after)
print(f"  Token count: {tokens_after} tokens")

# Calculate reduction
if tokens_before > 0:
    reduction_pct = ((tokens_before - tokens_after) / tokens_before) * 100
    tokens_saved = tokens_before - tokens_after
    print(f"  Reduction: {reduction_pct:.1f}% ({tokens_saved} tokens saved)")

if memories_after:
    print("\nSummarized memory:")
    print(f"  {memories_after[0].memory}")
else:
    print("\n No memories found after optimization")
