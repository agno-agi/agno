"""
Memory optimization using the "summarize" strategy.

When agent memories grow too large, you can use memory optimization to compress
them while preserving key information. The "summarize" strategy optimizes each
memory individually, maintaining the structure while reducing token usage.

Run: python cookbook/memory/09_memory_summarize_strategy.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, SummarizeStrategy
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

user_id = "user1"

# Create agent with memory enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    enable_user_memories=True,
)

# Create some memories for a user
print("Creating memories...")
agent.print_response(
    "My name is John Smith and I work as a senior software engineer at a fast-growing tech startup in Silicon Valley. "
    "I've been in this role for about 3 years now and I'm really passionate about what I do. "
    "The company focuses on building cloud infrastructure tools and I lead a small team of 5 engineers. "
    "Before this, I worked at two other companies doing backend development and DevOps work.",
    user_id=user_id,
)
agent.print_response(
    "I absolutely love Python programming - it's my favorite language by far. I've been coding in Python for over 8 years now. "
    "I'm particularly interested in building AI and machine learning applications. Recently I've been exploring large language models, "
    "natural language processing, and how to integrate AI capabilities into production systems. "
    "I also enjoy working with frameworks like FastAPI for building APIs and Django for web applications.",
    user_id=user_id,
)
agent.print_response(
    "I'm currently working on a really exciting project that involves using LLMs and vector databases to build an intelligent search system. "
    "We're using PostgreSQL with pgvector for storing embeddings, and we're experimenting with different chunking strategies. "
    "The project has been challenging but incredibly rewarding. We're dealing with millions of documents and need to optimize for both "
    "retrieval accuracy and speed. I've learned a ton about semantic search and RAG architectures in the process.",
    user_id=user_id,
)
agent.print_response(
    "In my free time, I really enjoy hiking in the mountains near where I live. I try to go at least twice a month when the weather is good. "
    "There's something really peaceful about being out in nature and disconnecting from technology for a while. "
    "I also play guitar - I've been playing for about 5 years now. I mostly play blues and rock music. "
    "I'm not great at it yet but I practice a few times a week and I'm slowly getting better. "
    "Music is a great creative outlet that balances out all the technical work I do during the day.",
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
    token_limit=150,  # Target token limit
    strategy="summarize",  # Optimize each memory individually
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

print("\nOptimized memories:")
for i, memory in enumerate(memories_after, 1):
    print(f"  {i}. {memory.memory}")
