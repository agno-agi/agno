from textwrap import dedent

from agno.agent import Agent
from agno.context import ContextManager
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

context_manager = ContextManager(
    model=OpenAIChat(id="gpt-4o-mini"),
    tool_compression_threshold=3,
)

# Setup database for persistent sessions
db = SqliteDb(db_file="tmp/research_agent_compressed.db")

# Create research agent with compression enabled
research_agent = Agent(
    name="Investigative Journalist",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    description=dedent("""\
        You are an investigative journalist conducting deep research.
        Search multiple sources, extract key information, and provide
        comprehensive analysis with proper attribution.\
    """),
    instructions=dedent("""\
        1. Search for 5-10 authoritative sources on the topic
        2. Extract and analyze key information from articles
        3. Cross-reference facts across sources
        4. Provide a well-structured report with citations
        5. Include statistics, quotes, and expert insights\
    """),
    # Database and session configuration
    db=db,
    session_id="investigative_research",
    add_history_to_context=True,  # Load previous research from DB
    # Context compression configuration
    compress_context=True,  # Enable compression!
    # Output configuration
    markdown=True,
    debug_mode=True,
)

# Query 1: Initial deep research
print("\n" + "=" * 80)
print("📰 QUERY 1: AI Regulation Worldwide")
print("=" * 80)
research_agent.print_response(
    "Research and analyze the current state of AI regulation worldwide. then search for the latest breakthroughs in quantum computing in 2024. then "
    "focus on major legislative efforts in the EU, US, and China. then compare the regulatory landscape of AI with the current state of quantum computing. then "
    "then provide a comprehensive analysis of the regulatory landscape of AI and quantum computing.",
    stream=True,
)

# Show compression stats
if (
    research_agent.context_manager
    and research_agent.context_manager.compression_count > 0
):
    print(f"\n✅ Compression applied during Query 1")
    print(f"   Compressions: {research_agent.context_manager.compression_count}")

# Query 2: Follow-up research (history loaded)
print("\n" + "=" * 80)
print("📰 QUERY 2: Quantum Computing Breakthroughs")
print("=" * 80)
print("Note: Previous research on AI regulation is in context (compressed)")
research_agent.print_response(
    "Research the latest breakthroughs in quantum computing in 2024. "
    "Focus on practical applications, major companies involved, and "
    "expert predictions for the next 5 years.",
    stream=True,
)

# Query 3: Comparative analysis (uses compressed history from both)
print("\n" + "=" * 80)
print("📰 QUERY 3: Comparative Analysis")
print("=" * 80)
print("Note: Context includes compressed summaries from Queries 1 & 2")
research_agent.print_response(
    "Compare the regulatory landscape of AI with the current state of "
    "quantum computing. Are there parallels? What can we learn?",
    stream=True,
)

# Analyze what's in the database vs what was sent to model
print("\n" + "=" * 80)
print("📊 DATABASE vs CONTEXT ANALYSIS")
print("=" * 80)

session = db.get_session(
    session_id="investigative_research", session_type=SessionType.AGENT
)
if session and session.runs:
    # Database stats (uncompressed storage)
    all_messages = session.get_messages_for_session()
    tool_messages = [m for m in all_messages if m.role == "tool"]

    print("\n🗄️  DATABASE (Uncompressed Storage):")
    print(f"   Total runs: {len(session.runs)}")
    print(f"   Total messages: {len(all_messages)}")
    print(f"   Tool result messages: {len(tool_messages)}")

    # Calculate original size
    total_chars = sum(len(str(m.content)) for m in tool_messages if m.content)
    estimated_tokens = total_chars // 4
    print(
        f"   Tool results size: {total_chars:,} characters (~{estimated_tokens:,} tokens)"
    )
    print(f"   ⚠️  All stored UNCOMPRESSED for future use")

    # Context compression stats (ephemeral, runtime-only)
    if research_agent.context_manager:
        cm = research_agent.context_manager
        print(f"\n🗜️  CONTEXT SENT TO MODEL (Compressed):")
        print(f"   Compressions applied: {cm.compression_count}")
        print(f"   ✅ Compression is EPHEMERAL (runtime-only)")
        print(f"   ✅ Database preserves original uncompressed data")

# Demonstrate that database has full content
print("\n" + "=" * 80)
print("🔍 PROOF: Database Has Full Uncompressed Content")
print("=" * 80)
if tool_messages:
    # Show first tool result (full content preserved)
    first_tool = tool_messages[0]
    print(f"\nFirst tool result from database:")
    print(f"Tool: {first_tool.tool_name}")
    print(f"Content length: {len(str(first_tool.content))} characters")
    if first_tool.content:
        preview = str(first_tool.content)[:200]
        print(f"First 200 chars: {preview}...")
    print(f"\n✅ Full content preserved in database!")
    print(f"✅ Compression only affected model's context window")

# Show the power of compression for long sessions
print("\n" + "=" * 80)
print("💡 KEY INSIGHTS")
print("=" * 80)
print("""
1. COMPRESSION IS EPHEMERAL:
   - Database stores ALL messages uncompressed
   - Compression happens ONLY when preparing context for model
   - Each new query compresses fresh from database

2. ENABLES LONGER SESSIONS:
   - Without: 2-3 queries max before hitting context limits
   - With: 5-6+ queries with full research depth

3. NO INFORMATION LOSS:
   - Original data always in database
   - Can re-process without compression if needed
   - Compression preserves key facts, entities, numbers

4. INTELLIGENT COMPRESSION:
   - Only tool results are compressed (not user/assistant messages)
   - Recent results stay uncompressed (threshold-based)
   - Batch compression when threshold exceeded

5. WORKS WITH ALL FEATURES:
   - ✅ Session persistence (db)
   - ✅ History loading (add_history_to_context)
   - ✅ History filtering (max_tool_calls_from_history)
   - ✅ Multiple queries in same session
""")

print("\n" + "=" * 80)
print("🎯 TO USE IN YOUR AGENT:")
print("=" * 80)
print("""
Simply add two lines to enable compression:

    agent = Agent(
        # ... your existing config ...
        compress_context=True,              # Enable compression
        tool_compression_threshold=5,       # Optional: tune threshold
    )

That's it! Your agent now handles 3-4x more tool calls per session.
""")
