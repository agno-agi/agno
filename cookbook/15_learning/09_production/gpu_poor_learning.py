"""
GPU-Poor Learning
================

Cost-effective learning strategies for resource-constrained environments.
Optimize learning without expensive infrastructure.

Key Concepts:
- Efficient extraction strategies
- Minimal embedding approaches
- Smart caching
- Batched processing

Run: python -m cookbook.production.gpu_poor_learning
"""

from agno.learn import LearningMachine, LearningMode

# =============================================================================
# COST BREAKDOWN
# =============================================================================


def show_cost_breakdown():
    """Show where costs come from in learning systems."""

    print("=" * 60)
    print("COST BREAKDOWN")
    print("=" * 60)

    print("""
    Where the costs come from:
    
    ┌─────────────────────────────────────────────────────────┐
    │              COST SOURCES                               │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  1. EXTRACTION (LLM calls)         ~60% of cost         │
    │     • Analyzing conversations                           │
    │     • Generating structured output                      │
    │     • Multiple calls per conversation                   │
    │                                                         │
    │  2. EMBEDDINGS (vector generation)  ~25% of cost        │
    │     • Embedding extracted items                         │
    │     • Embedding search queries                          │
    │     • Re-embedding on updates                           │
    │                                                         │
    │  3. STORAGE (database)              ~10% of cost        │
    │     • Vector storage                                    │
    │     • Metadata storage                                  │
    │     • Backups                                           │
    │                                                         │
    │  4. SEARCH (retrieval)              ~5% of cost         │
    │     • Vector similarity search                          │
    │     • Ranking and filtering                             │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    
    Monthly cost example (10K conversations):
    
    ┌─────────────────────────────────────────────────────────┐
    │  Default setup:                                         │
    │  • Extraction: 10K × 20 msgs × $0.003 = $600            │
    │  • Embeddings: 50K items × $0.0001 = $5                 │
    │  • Storage: ~$20                                        │
    │  • Search: ~$5                                          │
    │  Total: ~$630/month                                     │
    ├─────────────────────────────────────────────────────────┤
    │  Optimized setup:                                       │
    │  • Extraction: 10K × 2 triggers × $0.001 = $20          │
    │  • Embeddings: 10K items × $0.0001 = $1                 │
    │  • Storage: ~$10                                        │
    │  • Search: ~$2                                          │
    │  Total: ~$33/month (95% reduction!)                     │
    └─────────────────────────────────────────────────────────┘
    """)


# =============================================================================
# EXTRACTION OPTIMIZATION
# =============================================================================


def demo_extraction_optimization():
    """Show extraction cost optimization."""

    print("\n" + "=" * 60)
    print("EXTRACTION OPTIMIZATION")
    print("=" * 60)

    print("""
    Strategies to reduce extraction costs:
    
    ┌─────────────────────────────────────────────────────────┐
    │  1. SMART TRIGGERING                                    │
    ├─────────────────────────────────────────────────────────┤
    │  Instead of extracting every message, trigger only when │
    │  there's likely valuable information:                   │
    │                                                         │
    │  • User shares personal info (name, job, preferences)   │
    │  • New entities mentioned                               │
    │  • Conversation topic changes significantly             │
    │  • User corrects previous information                   │
    │                                                         │
    │  Skip extraction for:                                   │
    │  • Simple Q&A                                           │
    │  • Short messages (<20 words)                           │
    │  • Continuation without new info                        │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  2. USE SMALLER MODELS                                  │
    ├─────────────────────────────────────────────────────────┤
    │  Extraction doesn't need GPT-4:                         │
    │                                                         │
    │  GPT-4:    $30/1M tokens  → High cost                   │
    │  GPT-3.5:  $0.5/1M tokens → 60x cheaper                 │
    │  Claude Haiku: $0.25/1M  → 120x cheaper                 │
    │  Local LLM: ~$0          → Free (compute only)          │
    │                                                         │
    │  For structured extraction, smaller models work well!   │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  3. BATCH END-OF-CONVERSATION                           │
    ├─────────────────────────────────────────────────────────┤
    │  Instead of extracting during conversation:             │
    │                                                         │
    │  • Collect all messages                                 │
    │  • Extract once at conversation end                     │
    │  • Process in batches (e.g., hourly)                    │
    │                                                         │
    │  Trade-off: Less real-time, but much cheaper            │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    from agno.learn import LearningMachine, LearningMode

    # Cost-optimized configuration
    machine = LearningMachine(
        user_profile={
            "enabled": True,
            "model": "gpt-3.5-turbo",  # Cheaper model
            "extract_on": "conversation_end",  # Not every message
        },
        entity_memory={
            "enabled": True,
            "model": "gpt-3.5-turbo",
            "extract_on": "trigger",  # Only when triggered
            "triggers": ["new_entity", "entity_update"]
        },
        learned_knowledge={
            "enabled": True,
            "model": "gpt-3.5-turbo",
            "extract_on": "batch",  # Batch processing
            "batch_interval": "1h"
        },
        user_id=user_id
    )
    """)


# =============================================================================
# EMBEDDING OPTIMIZATION
# =============================================================================


def demo_embedding_optimization():
    """Show embedding cost optimization."""

    print("\n" + "=" * 60)
    print("EMBEDDING OPTIMIZATION")
    print("=" * 60)

    print("""
    Strategies to reduce embedding costs:
    
    ┌─────────────────────────────────────────────────────────┐
    │  1. USE SMALLER EMBEDDING MODELS                        │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Model                  Dimensions  Cost/1M tokens      │
    │  ─────────────────────────────────────────────────      │
    │  text-embedding-3-large   3072      $0.13               │
    │  text-embedding-3-small   1536      $0.02 (6x cheaper)  │
    │  text-embedding-ada-002   1536      $0.10               │
    │                                                         │
    │  For most use cases, small models work fine!            │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  2. CACHE EMBEDDINGS                                    │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  • Cache query embeddings (same queries repeat)         │
    │  • Don't re-embed unchanged content                     │
    │  • Use content hash as cache key                        │
    │                                                         │
    │  Cache hit rate of 30% = 30% cost reduction             │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  3. REDUCE EMBEDDING FREQUENCY                          │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  • Only embed truly searchable content                  │
    │  • Store metadata separately (no embedding needed)      │
    │  • Batch embedding operations                           │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  4. LOCAL EMBEDDINGS                                    │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Run embedding models locally:                          │
    │                                                         │
    │  • sentence-transformers (free, good quality)           │
    │  • FastEmbed (optimized for speed)                      │
    │  • Ollama embeddings (local LLM)                        │
    │                                                         │
    │  Cost: $0 (just compute)                                │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 LOCAL EMBEDDINGS:")
    print("-" * 40)
    print("""
    from sentence_transformers import SentenceTransformer
    
    class LocalEmbedder:
        '''Free local embeddings.'''
        
        def __init__(self, model_name="all-MiniLM-L6-v2"):
            self.model = SentenceTransformer(model_name)
            self.cache = {}
        
        def embed(self, text: str) -> list:
            # Check cache
            cache_key = hash(text)
            if cache_key in self.cache:
                return self.cache[cache_key]
            
            # Generate embedding
            embedding = self.model.encode(text).tolist()
            
            # Cache result
            self.cache[cache_key] = embedding
            return embedding
        
        def embed_batch(self, texts: list) -> list:
            # Filter out cached
            uncached = [t for t in texts if hash(t) not in self.cache]
            
            if uncached:
                embeddings = self.model.encode(uncached)
                for t, e in zip(uncached, embeddings):
                    self.cache[hash(t)] = e.tolist()
            
            return [self.cache[hash(t)] for t in texts]
    """)


# =============================================================================
# MINIMAL CONFIGURATION
# =============================================================================


def demo_minimal_config():
    """Show minimal cost configuration."""

    print("\n" + "=" * 60)
    print("MINIMAL COST CONFIGURATION")
    print("=" * 60)

    print("""
    The cheapest viable configuration:
    """)

    print("\n💻 CONFIGURATION:")
    print("-" * 40)
    print("""
    from agno.learn import LearningMachine, LearningMode

    # Absolute minimum cost configuration
    def create_budget_learning_machine(user_id: str):
        return LearningMachine(
            # Only user profile - highest value, lowest cost
            user_profile={
                "enabled": True,
                "model": "gpt-3.5-turbo",
                "max_facts": 20,  # Limit stored facts
                "extract_on": "conversation_end"
            },
            
            # Disable entity memory (high volume)
            entity_memory=False,
            
            # Disable learned knowledge (needs curation)
            learned_knowledge=False,
            
            # Session context is nearly free
            session_context=True,
            
            user_id=user_id
        )
    
    # Estimated cost: ~$5/month for 10K conversations
    
    # Step up: Add entity memory when needed
    def create_moderate_learning_machine(user_id: str):
        return LearningMachine(
            user_profile={
                "enabled": True,
                "model": "gpt-3.5-turbo",
                "extract_on": "conversation_end"
            },
            entity_memory={
                "enabled": True,
                "model": "gpt-3.5-turbo",
                "max_entities": 100,
                "extract_on": "trigger"  # Only on new entities
            },
            learned_knowledge=False,
            session_context=True,
            user_id=user_id
        )
    
    # Estimated cost: ~$20/month for 10K conversations
    """)


# =============================================================================
# STORAGE OPTIMIZATION
# =============================================================================


def demo_storage_optimization():
    """Show storage cost optimization."""

    print("\n" + "=" * 60)
    print("STORAGE OPTIMIZATION")
    print("=" * 60)

    print("""
    Reduce storage costs:
    
    ┌─────────────────────────────────────────────────────────┐
    │  1. CHOOSE RIGHT STORAGE                                │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Option          Cost/GB/mo   Best For                  │
    │  ────────────────────────────────────────────           │
    │  Pinecone        $70          Easy, managed             │
    │  Weaviate Cloud  $25          Feature-rich              │
    │  Supabase        $0.125       Budget, Postgres          │
    │  Self-hosted PG  $5-10        Control, scale            │
    │  SQLite + local  ~$0          Development, small scale  │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  2. DATA LIFECYCLE                                      │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  • Archive old sessions (move to cold storage)          │
    │  • Delete stale entities (not accessed 90+ days)        │
    │  • Summarize old conversations (keep summary only)      │
    │  • Set max items per user                               │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  3. COMPRESSION                                         │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  • Use smaller embedding dimensions (512 vs 1536)       │
    │  • Compress metadata (remove redundant fields)          │
    │  • Binary quantization for vectors (8x smaller)         │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)


# =============================================================================
# PROGRESSIVE ENHANCEMENT
# =============================================================================


def demo_progressive_enhancement():
    """Show how to add features as budget allows."""

    print("\n" + "=" * 60)
    print("PROGRESSIVE ENHANCEMENT")
    print("=" * 60)

    print("""
    Start minimal, add features as needed:
    
    ┌─────────────────────────────────────────────────────────┐
    │  LEVEL 0: FREE                                          │
    ├─────────────────────────────────────────────────────────┤
    │  • session_context only (in-memory)                     │
    │  • No persistence between sessions                      │
    │  • Good for: Prototypes, demos                          │
    └─────────────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │  LEVEL 1: ~$5/month                                     │
    ├─────────────────────────────────────────────────────────┤
    │  • + user_profile (end-of-conversation extraction)      │
    │  • + SQLite storage                                     │
    │  • Good for: Small apps, side projects                  │
    └─────────────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │  LEVEL 2: ~$30/month                                    │
    ├─────────────────────────────────────────────────────────┤
    │  • + entity_memory (triggered extraction)               │
    │  • + Supabase storage                                   │
    │  • + local embeddings                                   │
    │  • Good for: Growing apps, B2B tools                    │
    └─────────────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │  LEVEL 3: ~$100/month                                   │
    ├─────────────────────────────────────────────────────────┤
    │  • + learned_knowledge (always extraction)              │
    │  • + managed vector DB                                  │
    │  • + cloud embeddings                                   │
    │  • Good for: Production apps, paid products             │
    └─────────────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │  LEVEL 4: $500+/month                                   │
    ├─────────────────────────────────────────────────────────┤
    │  • Full real-time extraction                            │
    │  • GPT-4 for extraction                                 │
    │  • High-performance vector search                       │
    │  • Good for: Enterprise, high-value use cases           │
    └─────────────────────────────────────────────────────────┘
    """)


# =============================================================================
# COST MONITORING
# =============================================================================


def demo_cost_monitoring():
    """Show cost monitoring strategies."""

    print("\n" + "=" * 60)
    print("COST MONITORING")
    print("=" * 60)

    print("""
    Track and control costs:
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class CostTracker:
        '''Track learning system costs.'''
        
        def __init__(self):
            self.costs = {
                "extraction": 0,
                "embeddings": 0,
                "storage": 0,
                "search": 0
            }
            self.counts = {
                "extractions": 0,
                "embeddings": 0,
                "searches": 0
            }
        
        def record_extraction(self, model: str, tokens: int):
            rates = {
                "gpt-4": 0.03 / 1000,
                "gpt-3.5-turbo": 0.0005 / 1000,
                "claude-haiku": 0.00025 / 1000
            }
            cost = tokens * rates.get(model, 0.001 / 1000)
            self.costs["extraction"] += cost
            self.counts["extractions"] += 1
        
        def record_embedding(self, model: str, tokens: int):
            rates = {
                "text-embedding-3-small": 0.00002 / 1000,
                "text-embedding-3-large": 0.00013 / 1000,
                "local": 0
            }
            cost = tokens * rates.get(model, 0)
            self.costs["embeddings"] += cost
            self.counts["embeddings"] += 1
        
        def get_report(self):
            total = sum(self.costs.values())
            return {
                "total_cost": total,
                "breakdown": self.costs,
                "counts": self.counts,
                "avg_cost_per_extraction": (
                    self.costs["extraction"] / max(self.counts["extractions"], 1)
                )
            }
        
        def check_budget(self, budget: float) -> bool:
            '''Return True if under budget.'''
            return sum(self.costs.values()) < budget
    
    # Usage
    tracker = CostTracker()
    
    # After each operation
    tracker.record_extraction("gpt-3.5-turbo", 500)
    tracker.record_embedding("text-embedding-3-small", 100)
    
    # Check status
    if not tracker.check_budget(100):  # $100 budget
        # Switch to cheaper options or pause learning
        pass
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("💰 GPU-POOR LEARNING")
    print("=" * 60)
    print("Cost-effective learning strategies")
    print()

    show_cost_breakdown()
    demo_extraction_optimization()
    demo_embedding_optimization()
    demo_minimal_config()
    demo_storage_optimization()
    demo_progressive_enhancement()
    demo_cost_monitoring()

    print("\n" + "=" * 60)
    print("✅ GPU-poor learning guide complete!")
    print("=" * 60)
