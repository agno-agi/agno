"""Customer Support - A realistic frustrated customer journey.

This example shows a single customer with a complex sync issue.
The conversation evolves from confusion to frustration to resolution
over ~15 messages. Uses AUTOMATIC memory extraction (no explicit tools).

Memory layers populated automatically:
- Profile: company, role, plan type, technical level
- Policy: wants quick escalation, prefers technical details
- Knowledge: issue details, file types, usage patterns
- Feedback: frustration signals -> satisfaction at resolution
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryManagerV2
from agno.models.openai import OpenAIChat

# Database for customer profiles
db = SqliteDb(db_file="tmp/support_memory.db")

# AUTOMATIC memory extraction - no tools, extracts in background
memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),  # Extraction model
)

# Support agent
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager_v2=memory,
    update_memory_on_run=True,  # Auto-extract after each message
    instructions=(
        "You are a customer support agent for CloudSync, a file synchronization "
        "SaaS product. Be helpful, empathetic, and professional. Ask clarifying "
        "questions when needed. Escalate complex issues appropriately."
    ),
    markdown=True,
)

USER_ID = "marcus_techflow"


def show_customer_profile():
    """Show what automatic extraction has learned about this customer."""
    print("\n" + "=" * 70)
    print("CUSTOMER PROFILE (Auto-Extracted)")
    print("=" * 70)

    user = memory.get_user(USER_ID)
    if not user:
        print("(no data yet)")
        return

    # Profile
    if user.user_profile:
        print("\n[CUSTOMER INFO]")
        for k, v in user.user_profile.items():
            print(f"  {k}: {v}")

    # Policies/Preferences
    policies = user.memory_layers.get("policies", {})
    if policies:
        print("\n[PREFERENCES]")
        for k, v in policies.items():
            print(f"  {k}: {v}")

    # Knowledge/Context
    knowledge = user.memory_layers.get("knowledge", [])
    if knowledge:
        print("\n[ISSUE CONTEXT]")
        for item in knowledge:
            if isinstance(item, dict):
                print(f"  {item.get('key', '?')}: {item.get('value', item)}")

    # Feedback signals
    feedback = user.memory_layers.get("feedback", {})
    if feedback and isinstance(feedback, dict):
        pos = feedback.get("positive", [])
        neg = feedback.get("negative", [])
        if pos or neg:
            print("\n[SATISFACTION SIGNALS]")
            for item in pos:
                print(f"  + {item}")
            for item in neg:
                print(f"  - {item}")

    # Show what gets injected
    print("\n" + "-" * 70)
    print("INJECTED INTO AGENT CONTEXT:")
    print("-" * 70)
    context = memory.compile_user_context(USER_ID)
    print(context if context else "(nothing yet)")


def chat(message: str):
    """Customer sends a message."""
    print(f"\n{'>' * 3} CUSTOMER: {message}")
    agent.print_response(message, user_id=USER_ID, stream=True)


# ============================================================
# THE SUPPORT TICKET - A realistic frustrated customer journey
# ============================================================

print("\n" + "#" * 70)
print("# SUPPORT TICKET: File Sync Issues")
print("#" * 70)

# --- Initial contact ---

chat("hi my files arent syncing. getting some kind of error")

chat("it says SYNC_TIMEOUT_504. what does that even mean")

chat(
    "im on the business plan i think? my company is TechFlow Inc. im the IT manager here"
)

# Check early extraction
print("\n" + "=" * 70)
print("CHECKPOINT: After initial contact")
show_customer_profile()

# --- Troubleshooting ---

chat(
    "yeah i tried restarting the app. still broken. this is blocking our whole team from accessing shared files"
)

chat(
    "you need more info? ok so the files that fail are around 80-100MB each. theyre video files from our marketing team"
)

chat(
    "we upload maybe 30-40 files a day. mostly in the morning when everyone syncs their work. is that too many?"
)

chat(
    "ok i tried that chunked upload setting you mentioned. its still failing on the bigger files. the small ones work fine"
)

# --- Frustration building ---

chat(
    "look this is really frustrating. weve been CloudSync customers for 2 years and never had issues like this before"
)

chat(
    "i dont want more troubleshooting steps. can you escalate this? i need to talk to an actual engineer who understands whats happening on the backend"
)

# Check mid-conversation extraction
print("\n" + "=" * 70)
print("CHECKPOINT: Customer frustration peak")
show_customer_profile()

# --- Resolution ---

chat(
    "[next day] hey so the engineer you connected me with yesterday - their fix worked! the new chunked upload mode with smaller chunk sizes solved everything"
)

chat(
    "yeah much better now. thanks for escalating quickly and not making me repeat myself 10 times. thats refreshing for support honestly"
)

chat(
    "one more thing before i go - can you explain WHY this was happening? i need to document it for my team so we know what to do if it happens again"
)

chat(
    "perfect that makes sense. large files hitting the timeout threshold. ill add that to our internal docs"
)

chat(
    "yeah ill definitely recommend CloudSync to other IT folks i know. you guys handled this way better than most support teams. have a good one"
)


# ============================================================
# FINAL: Complete customer profile
# ============================================================

print("\n" + "#" * 70)
print("# FINAL CUSTOMER PROFILE")
print("#" * 70)

show_customer_profile()

print("\n" + "=" * 70)
print("WHAT AUTOMATIC EXTRACTION LEARNED")
print("=" * 70)
print("""
Over 15 messages, the system AUTOMATICALLY extracted:

PROFILE:
- Company: TechFlow Inc
- Role: IT Manager  
- Plan: Business
- Customer tenure: 2 years

PREFERENCES:
- Wants quick escalation for complex issues
- Appreciates not repeating information
- Values technical explanations

CONTEXT:
- Issue: Large file sync timeouts (80-100MB video files)
- Usage: 30-40 files/day, morning peak
- Resolution: Smaller chunk sizes in chunked upload mode

SATISFACTION JOURNEY:
- Started: Confused about error
- Middle: Frustrated, wanted escalation
- End: Satisfied, will recommend to others

All extracted automatically from natural conversation!
No save_user_info() tool calls - just background extraction.
""")
