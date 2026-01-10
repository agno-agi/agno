"""
Async Patterns
==============

Asynchronous patterns for production learning systems.

Key Concepts:
- Async/await best practices
- Concurrent operations
- Background processing
- Error handling and retries

Run: python -m cookbook.advanced.05_async_patterns
"""


# =============================================================================
# BASIC ASYNC USAGE
# =============================================================================


def demo_basic_async():
    """Show basic async patterns with LearningMachine."""

    print("=" * 60)
    print("BASIC ASYNC PATTERNS")
    print("=" * 60)

    print("""
    LearningMachine supports both sync and async interfaces:
    """)

    print("\n💻 SYNC VS ASYNC:")
    print("-" * 40)
    print("""
    from agno.learn import LearningMachine, LearningMode
    
    machine = LearningMachine(
        user_profile=True,
        entity_memory=True,
        user_id="user123"
    )
    
    # SYNCHRONOUS (blocking)
    result = machine.invoke({
        "messages": messages
    })
    
    # ASYNCHRONOUS (non-blocking)
    result = await machine.ainvoke({
        "messages": messages
    })
    
    # Use async when:
    # - Web servers (FastAPI, Starlette)
    # - High concurrency applications
    # - I/O bound operations
    # - Background processing
    """)


# =============================================================================
# CONCURRENT OPERATIONS
# =============================================================================


def demo_concurrent_operations():
    """Show concurrent operation patterns."""

    print("\n" + "=" * 60)
    print("CONCURRENT OPERATIONS")
    print("=" * 60)

    print("""
    Process multiple operations concurrently:
    
    ┌─────────────────────────────────────────────────────────┐
    │              SEQUENTIAL (SLOW)                          │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  user_profile ──────────────────────▶ 200ms             │
    │                 entity_memory ──────────────────▶ 300ms │
    │                                learned_knowledge ─────▶ │
    │                                                   250ms │
    │  Total: 750ms                                           │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │              CONCURRENT (FAST)                          │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  user_profile ──────────────────────▶ 200ms             │
    │  entity_memory ────────────────────────────▶ 300ms      │
    │  learned_knowledge ─────────────────────▶ 250ms         │
    │                                                         │
    │  Total: 300ms (max of all)                              │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 CONCURRENT RETRIEVAL:")
    print("-" * 40)
    print("""
    async def get_all_context(user_id: str, query: str):
        '''Retrieve from all stores concurrently.'''
        
        # Start all retrievals simultaneously
        profile_task = asyncio.create_task(
            user_profile_store.get(user_id)
        )
        entity_task = asyncio.create_task(
            entity_store.search(query, limit=5)
        )
        knowledge_task = asyncio.create_task(
            knowledge_store.search(query, limit=5)
        )
        
        # Wait for all to complete
        profile, entities, knowledge = await asyncio.gather(
            profile_task,
            entity_task,
            knowledge_task
        )
        
        return {
            "profile": profile,
            "entities": entities,
            "knowledge": knowledge
        }
    """)

    print("\n💻 CONCURRENT PROCESSING:")
    print("-" * 40)
    print("""
    async def process_batch(conversations: List[Dict]):
        '''Process multiple conversations concurrently.'''
        
        # Create tasks for each conversation
        tasks = [
            process_conversation(conv) 
            for conv in conversations
        ]
        
        # Process with concurrency limit
        semaphore = asyncio.Semaphore(10)  # Max 10 concurrent
        
        async def limited_process(task):
            async with semaphore:
                return await task
        
        results = await asyncio.gather(
            *[limited_process(t) for t in tasks],
            return_exceptions=True  # Don't fail all if one fails
        )
        
        # Handle results
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        
        return successes, failures
    """)


# =============================================================================
# BACKGROUND PROCESSING
# =============================================================================


def demo_background_processing():
    """Show background processing patterns."""

    print("\n" + "=" * 60)
    print("BACKGROUND PROCESSING")
    print("=" * 60)

    print("""
    Process learning in background without blocking:
    
    ┌─────────────────────────────────────────────────────────┐
    │              REQUEST FLOW                               │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  User Request                                           │
    │       │                                                 │
    │       ▼                                                 │
    │  ┌─────────────┐                                        │
    │  │  Generate   │───▶ Response to User (fast)            │
    │  │  Response   │                                        │
    │  └─────┬───────┘                                        │
    │        │                                                │
    │        ▼ (fire and forget)                              │
    │  ┌─────────────┐                                        │
    │  │  Background │                                        │
    │  │  Learning   │───▶ Update stores (async)              │
    │  └─────────────┘                                        │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 BACKGROUND TASK:")
    print("-" * 40)
    print("""
    class BackgroundLearner:
        '''Process learning in background.'''
        
        def __init__(self, machine):
            self.machine = machine
            self.queue = asyncio.Queue()
            self.running = False
        
        async def start(self):
            '''Start background worker.'''
            self.running = True
            asyncio.create_task(self._worker())
        
        async def stop(self):
            '''Stop background worker.'''
            self.running = False
            await self.queue.join()
        
        async def _worker(self):
            '''Process queued learning tasks.'''
            while self.running:
                try:
                    task = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                    await self._process(task)
                    self.queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Background learning error: {e}")
        
        async def _process(self, task):
            '''Process a single learning task.'''
            await self.machine.extract(
                messages=task["messages"],
                stores=task.get("stores", ["learned_knowledge"])
            )
        
        def schedule(self, messages: List, stores: List = None):
            '''Schedule learning for background processing.'''
            self.queue.put_nowait({
                "messages": messages,
                "stores": stores or ["learned_knowledge"],
                "scheduled_at": datetime.now()
            })
    
    # Usage in web handler
    async def chat_handler(request):
        messages = request.messages
        
        # Generate response immediately
        response = await generate_response(messages)
        
        # Schedule learning in background (non-blocking)
        background_learner.schedule(messages)
        
        return response
    """)


# =============================================================================
# ERROR HANDLING AND RETRIES
# =============================================================================


def demo_error_handling():
    """Show error handling and retry patterns."""

    print("\n" + "=" * 60)
    print("ERROR HANDLING AND RETRIES")
    print("=" * 60)

    print("""
    Robust error handling for production:
    """)

    print("\n💻 RETRY WITH BACKOFF:")
    print("-" * 40)
    print("""
    import asyncio
    from typing import TypeVar, Callable
    
    T = TypeVar('T')
    
    async def retry_with_backoff(
        fn: Callable[[], T],
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exceptions: tuple = (Exception,)
    ) -> T:
        '''Retry async function with exponential backoff.'''
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                return await fn()
            except exceptions as e:
                last_exception = e
                
                if attempt == max_retries - 1:
                    raise
                
                # Calculate delay with exponential backoff
                delay = min(base_delay * (2 ** attempt), max_delay)
                
                # Add jitter to prevent thundering herd
                delay *= (0.5 + random.random())
                
                logger.warning(
                    f"Attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                
                await asyncio.sleep(delay)
        
        raise last_exception
    
    # Usage
    async def save_with_retry(store, key, value):
        await retry_with_backoff(
            lambda: store.put(key, value),
            max_retries=3,
            exceptions=(ConnectionError, TimeoutError)
        )
    """)

    print("\n💻 GRACEFUL DEGRADATION:")
    print("-" * 40)
    print("""
    async def get_context_safely(user_id: str, query: str):
        '''Get context with graceful fallbacks.'''
        
        context = {}
        
        # Try user profile - important but not critical
        try:
            context["profile"] = await asyncio.wait_for(
                user_profile_store.get(user_id),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            logger.warning("User profile timed out")
            context["profile"] = None
        except Exception as e:
            logger.error(f"User profile error: {e}")
            context["profile"] = None
        
        # Try entity memory - enhances but not required
        try:
            context["entities"] = await asyncio.wait_for(
                entity_store.search(query),
                timeout=3.0
            )
        except Exception as e:
            logger.error(f"Entity search error: {e}")
            context["entities"] = []
        
        # Response can proceed with partial context
        return context
    """)


# =============================================================================
# STREAMING WITH LEARNING
# =============================================================================


def demo_streaming():
    """Show streaming patterns with learning."""

    print("\n" + "=" * 60)
    print("STREAMING WITH LEARNING")
    print("=" * 60)

    print("""
    Stream responses while learning in background:
    
    ┌─────────────────────────────────────────────────────────┐
    │              STREAMING FLOW                             │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  User Message                                           │
    │       │                                                 │
    │       ▼                                                 │
    │  ┌─────────────┐                                        │
    │  │   Stream    │──▶ [chunk1][chunk2][chunk3]...         │
    │  │   Response  │                      │                 │
    │  └─────────────┘                      │                 │
    │                                       ▼                 │
    │                              [Complete Response]         │
    │                                       │                 │
    │                                       ▼                 │
    │                              ┌─────────────┐            │
    │                              │   Learn     │            │
    │                              │  (async)    │            │
    │                              └─────────────┘            │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    async def stream_with_learning(
        messages: List[Dict],
        machine: LearningMachine
    ):
        '''Stream response and learn after completion.'''
        
        full_response = []
        
        # Stream the response
        async for chunk in llm.astream(messages):
            full_response.append(chunk)
            yield chunk
        
        # After stream complete, trigger learning
        complete_response = "".join(full_response)
        
        # Add assistant response to messages
        messages_with_response = messages + [
            {"role": "assistant", "content": complete_response}
        ]
        
        # Schedule background learning (don't await)
        asyncio.create_task(
            machine.extract(
                messages=messages_with_response,
                stores=["user_profile", "entity_memory"]
            )
        )
    
    # FastAPI example
    @app.post("/chat/stream")
    async def chat_stream(request: ChatRequest):
        return StreamingResponse(
            stream_with_learning(request.messages, machine),
            media_type="text/event-stream"
        )
    """)


# =============================================================================
# ASYNC CONTEXT MANAGERS
# =============================================================================


def demo_context_managers():
    """Show async context manager patterns."""

    print("\n" + "=" * 60)
    print("ASYNC CONTEXT MANAGERS")
    print("=" * 60)

    print("""
    Proper resource management with async:
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class ManagedLearningMachine:
        '''Learning machine with proper lifecycle management.'''
        
        def __init__(self, config):
            self.config = config
            self.machine = None
            self.stores = {}
        
        async def __aenter__(self):
            '''Initialize stores on entry.'''
            # Initialize all stores
            self.stores["user_profile"] = await create_store(
                self.config.user_profile
            )
            self.stores["entity"] = await create_store(
                self.config.entity_memory
            )
            
            # Create machine
            self.machine = LearningMachine(
                user_profile={"store": self.stores["user_profile"]},
                entity_memory={"store": self.stores["entity"]},
                **self.config.base
            )
            
            return self.machine
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            '''Cleanup on exit.'''
            # Close all stores
            for store in self.stores.values():
                await store.close()
            
            # Don't suppress exceptions
            return False
    
    # Usage
    async def main():
        config = LearningConfig(...)
        
        async with ManagedLearningMachine(config) as machine:
            result = await machine.ainvoke({
                "messages": messages
            })
        # Stores automatically closed here
    """)


# =============================================================================
# BEST PRACTICES SUMMARY
# =============================================================================


def show_best_practices():
    """Display async best practices."""

    print("\n" + "=" * 60)
    print("ASYNC BEST PRACTICES")
    print("=" * 60)

    print("""
    ✅ DO:
    
    1. Use asyncio.gather() for concurrent I/O
    2. Set timeouts on all external calls
    3. Use semaphores to limit concurrency
    4. Handle exceptions gracefully with fallbacks
    5. Use background tasks for non-critical learning
    6. Close resources properly with context managers
    
    ❌ DON'T:
    
    1. Block the event loop with sync code
    2. Create unlimited concurrent tasks
    3. Ignore exceptions in background tasks
    4. Forget to handle timeouts
    5. Mix sync and async code carelessly
    
    📊 PERFORMANCE TIPS:
    
    1. Profile to find actual bottlenecks
    2. Cache frequently accessed data
    3. Batch operations when possible
    4. Use connection pools for databases
    5. Consider read replicas for heavy read loads
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("⚡ ASYNC PATTERNS")
    print("=" * 60)
    print("Asynchronous patterns for production systems")
    print()

    demo_basic_async()
    demo_concurrent_operations()
    demo_background_processing()
    demo_error_handling()
    demo_streaming()
    demo_context_managers()
    show_best_practices()

    print("\n" + "=" * 60)
    print("✅ Async patterns guide complete!")
    print("=" * 60)
