"""
Extraction Timing
=================

When and how to trigger learning extraction for optimal results.

Key Concepts:
- Synchronous vs asynchronous extraction
- Trigger conditions
- Rate limiting and batching
- Cost vs freshness tradeoffs

Run: python -m cookbook.advanced.03_extraction_timing
"""


# =============================================================================
# EXTRACTION MODES
# =============================================================================


def demo_extraction_modes():
    """Show different extraction timing modes."""

    print("=" * 60)
    print("EXTRACTION MODES")
    print("=" * 60)

    print("""
    When extraction happens:
    
    ┌─────────────────────────────────────────────────────────┐
    │                 SYNCHRONOUS                             │
    ├─────────────────────────────────────────────────────────┤
    │  Timing: During the conversation turn                   │
    │  Latency: Adds 500-2000ms to response                   │
    │  Freshness: Immediate                                   │
    │  Use when: Data needed in next turn                     │
    │                                                         │
    │  User → [Extract] → [Generate Response] → User          │
    │           ↓                                             │
    │         Store                                           │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │                ASYNCHRONOUS                             │
    ├─────────────────────────────────────────────────────────┤
    │  Timing: After response sent, in background             │
    │  Latency: None (response sent immediately)              │
    │  Freshness: Available next conversation                 │
    │  Use when: Data can wait, latency matters               │
    │                                                         │
    │  User → [Generate Response] → User                      │
    │                ↓                                        │
    │           [Queue] → [Extract] → Store                   │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │                   BATCHED                               │
    ├─────────────────────────────────────────────────────────┤
    │  Timing: Periodic job processes accumulated data        │
    │  Latency: None                                          │
    │  Freshness: Minutes to hours delayed                    │
    │  Use when: High volume, cost-sensitive                  │
    │                                                         │
    │  User → Response → User                                 │
    │          ↓                                              │
    │        [Log] → [Batch Job] → [Extract] → Store          │
    │               (every N min)                             │
    └─────────────────────────────────────────────────────────┘
    """)


# =============================================================================
# TRIGGER CONDITIONS
# =============================================================================


def demo_trigger_conditions():
    """Show when to trigger extraction."""

    print("\n" + "=" * 60)
    print("TRIGGER CONDITIONS")
    print("=" * 60)

    print("""
    Smart triggering saves cost and improves quality:
    
    ┌─────────────────────────────────────────────────────────┐
    │             ALWAYS EXTRACT                              │
    ├─────────────────────────────────────────────────────────┤
    │  • User explicitly shares personal info                 │
    │  • New entity mentioned (person, project, company)      │
    │  • User corrects previous information                   │
    │  • Conversation topic significantly changes             │
    │  • User expresses strong preference                     │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │             SKIP EXTRACTION                             │
    ├─────────────────────────────────────────────────────────┤
    │  • Simple Q&A (factual questions)                       │
    │  • User message is very short (<10 words)               │
    │  • Continuation of same topic (no new info)             │
    │  • Error messages or system interactions                │
    │  • Recent extraction covered same content               │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │             DELAYED EXTRACTION                          │
    ├─────────────────────────────────────────────────────────┤
    │  • Long conversation (batch at end)                     │
    │  • High-velocity chat (rate limit)                      │
    │  • Tentative information (wait for confirmation)        │
    │  • Complex analysis (needs full context)                │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 TRIGGER DETECTION:")
    print("-" * 40)
    print("""
    def should_extract(message, context):
        '''Determine if extraction should run.'''
        
        # Always extract conditions
        if contains_personal_info(message):
            return True, "sync"
        if mentions_new_entity(message, context.known_entities):
            return True, "sync"
        if is_correction(message, context.previous_facts):
            return True, "sync"
        
        # Skip extraction conditions
        if len(message.split()) < 10:
            return False, None
        if is_simple_question(message):
            return False, None
        if recently_extracted(context, threshold_minutes=5):
            return False, None
        
        # Default: async extraction
        return True, "async"
    """)


# =============================================================================
# RATE LIMITING
# =============================================================================


def demo_rate_limiting():
    """Show rate limiting strategies."""

    print("\n" + "=" * 60)
    print("RATE LIMITING")
    print("=" * 60)

    print("""
    Prevent excessive extraction costs:
    
    ┌─────────────────────────────────────────────────────────┐
    │               RATE LIMITS                               │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Per User:                                              │
    │  ├─ Max 10 extractions per minute                       │
    │  ├─ Max 100 extractions per hour                        │
    │  └─ Max 500 extractions per day                         │
    │                                                         │
    │  Per Conversation:                                      │
    │  ├─ Max 1 extraction per 30 seconds                     │
    │  ├─ Max 20 extractions per conversation                 │
    │  └─ Batch if conversation > 50 messages                 │
    │                                                         │
    │  Global:                                                │
    │  ├─ Max 1000 extractions per minute (system)            │
    │  └─ Queue overflow → delay non-critical                 │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 RATE LIMITER:")
    print("-" * 40)
    print("""
    class ExtractionRateLimiter:
        '''Rate limit extraction calls.'''
        
        def __init__(self):
            self.user_counts = defaultdict(lambda: {
                "minute": 0,
                "hour": 0,
                "day": 0,
                "last_reset": {}
            })
        
        def can_extract(self, user_id):
            counts = self.user_counts[user_id]
            self._maybe_reset(counts)
            
            if counts["minute"] >= 10:
                return False, "Rate limit: per-minute"
            if counts["hour"] >= 100:
                return False, "Rate limit: per-hour"
            if counts["day"] >= 500:
                return False, "Rate limit: per-day"
            
            return True, None
        
        def record_extraction(self, user_id):
            counts = self.user_counts[user_id]
            counts["minute"] += 1
            counts["hour"] += 1
            counts["day"] += 1
    """)


# =============================================================================
# CONVERSATION END EXTRACTION
# =============================================================================


def demo_conversation_end():
    """Show end-of-conversation extraction patterns."""

    print("\n" + "=" * 60)
    print("CONVERSATION END EXTRACTION")
    print("=" * 60)

    print("""
    Extract comprehensive summary at conversation end:
    
    ┌─────────────────────────────────────────────────────────┐
    │          DURING CONVERSATION                            │
    ├─────────────────────────────────────────────────────────┤
    │  • Light extraction (key facts only)                    │
    │  • Quick entity mentions                                │
    │  • Immediate needs captured                             │
    │                                                         │
    │  Messages: [M1] → [M2] → [M3] → ... → [Mn]              │
    │              ↓      ↓                                   │
    │          (light) (light)                                │
    └─────────────────────────────────────────────────────────┘
                            │
                            ▼ (conversation ends)
    ┌─────────────────────────────────────────────────────────┐
    │          END OF CONVERSATION                            │
    ├─────────────────────────────────────────────────────────┤
    │  • Full context analysis                                │
    │  • Relationship mapping                                 │
    │  • Pattern extraction                                   │
    │  • Session summary creation                             │
    │                                                         │
    │  Full transcript → [Deep Extract] → All stores          │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 END EXTRACTION:")
    print("-" * 40)
    print("""
    async def on_conversation_end(conversation):
        '''Comprehensive extraction when conversation ends.'''
        
        # Detect conversation end
        # - User explicitly ends ("thanks, goodbye")
        # - Timeout (no message for 30 min)
        # - UI signal (user closes chat)
        
        messages = conversation.messages
        
        # Skip if very short
        if len(messages) < 4:
            return
        
        # Full extraction with complete context
        await extract_comprehensive(
            messages=messages,
            stores=["user_profile", "entity_memory", "learned_knowledge"],
            mode="thorough"  # Use more tokens for better extraction
        )
        
        # Create session summary
        await create_session_summary(
            messages=messages,
            key_topics=extract_topics(messages),
            action_items=extract_action_items(messages),
            next_session_context=prepare_continuation(messages)
        )
    """)


# =============================================================================
# COST VS FRESHNESS
# =============================================================================


def demo_cost_freshness_tradeoff():
    """Show cost vs freshness tradeoffs."""

    print("\n" + "=" * 60)
    print("COST VS FRESHNESS TRADEOFFS")
    print("=" * 60)

    print("""
    Different strategies for different needs:
    
    ┌─────────────────────────────────────────────────────────┐
    │  Strategy      │ Cost  │ Freshness │ Best For          │
    ├─────────────────────────────────────────────────────────┤
    │  Every message │ $$$$  │ Immediate │ Critical real-time│
    │  Smart trigger │ $$    │ Near-time │ Most applications │
    │  End of conv   │ $     │ Delayed   │ Cost-sensitive    │
    │  Batch hourly  │ ¢     │ Hours     │ Analytics only    │
    └─────────────────────────────────────────────────────────┘
    
    Cost Breakdown (per 1000 conversations):
    
    ┌─────────────────────────────────────────────────────────┐
    │  Every message (avg 20 msgs/conv):                      │
    │    20,000 extraction calls × $0.01 = $200               │
    │                                                         │
    │  Smart trigger (avg 5 triggers/conv):                   │
    │    5,000 extraction calls × $0.01 = $50                 │
    │                                                         │
    │  End of conversation only:                              │
    │    1,000 extraction calls × $0.02 = $20                 │
    │    (larger context = higher per-call cost)              │
    │                                                         │
    │  Batch hourly:                                          │
    │    ~50 batch jobs × $0.10 = $5                          │
    │    (aggregated processing)                              │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n🎯 RECOMMENDATIONS:")
    print("-" * 40)
    print("""
    Consumer apps (chat assistants):
    → Smart trigger + end of conversation
    → Balance: Good freshness, moderate cost
    
    Enterprise apps (high-value interactions):
    → Smart trigger + sync for critical info
    → Accept higher cost for better experience
    
    Analytics/insights (non-real-time):
    → Batch extraction hourly/daily
    → Minimize cost, freshness not critical
    
    Hybrid approach:
    → Sync: User corrections, explicit preferences
    → Async: General learning, patterns
    → Batch: Cross-user insights, analytics
    """)


# =============================================================================
# IMPLEMENTATION EXAMPLE
# =============================================================================


def demo_implementation():
    """Show complete extraction timing implementation."""

    print("\n" + "=" * 60)
    print("IMPLEMENTATION EXAMPLE")
    print("=" * 60)

    print("""
    Complete extraction timing system:
    """)

    print("\n💻 CODE:")
    print("-" * 40)
    print("""
    class SmartExtractor:
        '''Intelligent extraction timing.'''
        
        def __init__(self, machine, config):
            self.machine = machine
            self.config = config
            self.rate_limiter = ExtractionRateLimiter()
            self.pending_queue = asyncio.Queue()
        
        async def process_message(self, message, context):
            '''Decide extraction timing for a message.'''
            
            # Check rate limits
            can_extract, reason = self.rate_limiter.can_extract(
                context.user_id
            )
            if not can_extract:
                await self.queue_for_later(message, context)
                return
            
            # Determine extraction need
            should_run, mode = should_extract(message, context)
            
            if not should_run:
                return
            
            if mode == "sync":
                # Extract now, before response
                await self.extract_sync(message, context)
            else:
                # Queue for background processing
                await self.queue_for_background(message, context)
        
        async def extract_sync(self, message, context):
            '''Synchronous extraction (blocks response).'''
            result = await self.machine.extract(
                messages=context.messages + [message],
                stores=["user_profile", "entity_memory"]
            )
            self.rate_limiter.record_extraction(context.user_id)
            return result
        
        async def queue_for_background(self, message, context):
            '''Queue for async processing.'''
            await self.pending_queue.put({
                "message": message,
                "context": context,
                "queued_at": datetime.now()
            })
        
        async def background_worker(self):
            '''Process queued extractions.'''
            while True:
                item = await self.pending_queue.get()
                try:
                    await self.machine.extract(
                        messages=item["context"].messages,
                        stores=["learned_knowledge"]
                    )
                except Exception as e:
                    logger.error(f"Background extraction failed: {e}")
                finally:
                    self.pending_queue.task_done()
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("⏱️ EXTRACTION TIMING")
    print("=" * 60)
    print("When and how to trigger learning extraction")
    print()

    demo_extraction_modes()
    demo_trigger_conditions()
    demo_rate_limiting()
    demo_conversation_end()
    demo_cost_freshness_tradeoff()
    demo_implementation()

    print("\n" + "=" * 60)
    print("✅ Extraction timing guide complete!")
    print("=" * 60)
