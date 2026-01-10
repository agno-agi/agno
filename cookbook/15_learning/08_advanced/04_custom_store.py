"""
Custom Store Implementation
===========================

Creating custom storage backends for the learning system.

Key Concepts:
- Store interface requirements
- Custom database integration
- Hybrid storage patterns
- Migration strategies

Run: python -m cookbook.advanced.04_custom_store
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# =============================================================================
# STORE INTERFACE
# =============================================================================


def demo_store_interface():
    """Show the store interface that custom stores must implement."""

    print("=" * 60)
    print("STORE INTERFACE")
    print("=" * 60)

    print("""
    Custom stores must implement these interfaces:
    
    ┌─────────────────────────────────────────────────────────┐
    │              BASE STORE INTERFACE                       │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Required Methods:                                      │
    │  ├─ get(key) → value                                    │
    │  ├─ put(key, value) → None                              │
    │  ├─ delete(key) → None                                  │
    │  ├─ list(prefix) → List[key]                            │
    │  └─ search(query, limit) → List[result]                 │
    │                                                         │
    │  Optional Methods:                                      │
    │  ├─ batch_get(keys) → Dict[key, value]                  │
    │  ├─ batch_put(items) → None                             │
    │  └─ close() → None                                      │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 BASE INTERFACE:")
    print("-" * 40)


class BaseStore(ABC):
    """Abstract base class for custom stores."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a value by key."""
        pass

    @abstractmethod
    async def put(self, key: str, value: Dict[str, Any]) -> None:
        """Store a value with key."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a value by key."""
        pass

    @abstractmethod
    async def list(self, prefix: str = "") -> List[str]:
        """List all keys with optional prefix filter."""
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Semantic search for relevant items."""
        pass

    # Optional batch operations
    async def batch_get(self, keys: List[str]) -> Dict[str, Any]:
        """Batch retrieve multiple keys."""
        return {k: await self.get(k) for k in keys}

    async def batch_put(self, items: Dict[str, Any]) -> None:
        """Batch store multiple items."""
        for k, v in items.items():
            await self.put(k, v)

    async def close(self) -> None:
        """Cleanup resources."""
        pass


# =============================================================================
# POSTGRES EXAMPLE
# =============================================================================


def demo_postgres_store():
    """Show PostgreSQL custom store implementation."""

    print("\n" + "=" * 60)
    print("POSTGRESQL STORE EXAMPLE")
    print("=" * 60)

    print("""
    PostgreSQL with pgvector for semantic search:
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    import asyncpg
    from pgvector.asyncpg import register_vector
    
    class PostgresStore(BaseStore):
        '''PostgreSQL store with vector search.'''
        
        def __init__(self, connection_string: str, table: str):
            self.connection_string = connection_string
            self.table = table
            self.pool = None
            self.embedder = None  # Your embedding model
        
        async def initialize(self):
            '''Set up connection pool and table.'''
            self.pool = await asyncpg.create_pool(self.connection_string)
            
            async with self.pool.acquire() as conn:
                await register_vector(conn)
                await conn.execute(f'''
                    CREATE TABLE IF NOT EXISTS {self.table} (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        embedding vector(1536),
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                ''')
                await conn.execute(f'''
                    CREATE INDEX IF NOT EXISTS {self.table}_embedding_idx
                    ON {self.table}
                    USING ivfflat (embedding vector_cosine_ops)
                ''')
        
        async def get(self, key: str) -> Optional[Dict]:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f'SELECT value FROM {self.table} WHERE key = $1',
                    key
                )
                return dict(row['value']) if row else None
        
        async def put(self, key: str, value: Dict) -> None:
            # Generate embedding for searchable content
            text = value.get('content', str(value))
            embedding = await self.embedder.embed(text)
            
            async with self.pool.acquire() as conn:
                await conn.execute(f'''
                    INSERT INTO {self.table} (key, value, embedding, updated_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = $2,
                        embedding = $3,
                        updated_at = NOW()
                ''', key, value, embedding)
        
        async def search(self, query: str, limit: int = 10) -> List[Dict]:
            query_embedding = await self.embedder.embed(query)
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(f'''
                    SELECT key, value, 
                           1 - (embedding <=> $1) as similarity
                    FROM {self.table}
                    ORDER BY embedding <=> $1
                    LIMIT $2
                ''', query_embedding, limit)
                
                return [
                    {**dict(row['value']), 'similarity': row['similarity']}
                    for row in rows
                ]
    """)


# =============================================================================
# REDIS EXAMPLE
# =============================================================================


def demo_redis_store():
    """Show Redis custom store implementation."""

    print("\n" + "=" * 60)
    print("REDIS STORE EXAMPLE")
    print("=" * 60)

    print("""
    Redis for fast caching with optional persistence:
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    import redis.asyncio as redis
    import json
    
    class RedisStore(BaseStore):
        '''Redis store for fast access.'''
        
        def __init__(self, url: str, prefix: str = "agno"):
            self.url = url
            self.prefix = prefix
            self.client = None
        
        async def initialize(self):
            self.client = await redis.from_url(self.url)
        
        def _key(self, key: str) -> str:
            return f"{self.prefix}:{key}"
        
        async def get(self, key: str) -> Optional[Dict]:
            data = await self.client.get(self._key(key))
            return json.loads(data) if data else None
        
        async def put(self, key: str, value: Dict) -> None:
            await self.client.set(
                self._key(key),
                json.dumps(value)
            )
        
        async def delete(self, key: str) -> None:
            await self.client.delete(self._key(key))
        
        async def list(self, prefix: str = "") -> List[str]:
            pattern = f"{self.prefix}:{prefix}*"
            keys = await self.client.keys(pattern)
            # Remove prefix from keys
            prefix_len = len(self.prefix) + 1
            return [k.decode()[prefix_len:] for k in keys]
        
        async def search(self, query: str, limit: int = 10) -> List[Dict]:
            # Redis doesn't support semantic search natively
            # Options:
            # 1. Use Redis Search module with vector similarity
            # 2. Fall back to prefix/pattern matching
            # 3. Hybrid: cache hot items, delegate search to primary store
            raise NotImplementedError(
                "Use RedisStack for vector search or hybrid approach"
            )
    """)


# =============================================================================
# HYBRID STORE
# =============================================================================


def demo_hybrid_store():
    """Show hybrid storage pattern."""

    print("\n" + "=" * 60)
    print("HYBRID STORE PATTERN")
    print("=" * 60)

    print("""
    Combine stores for optimal performance:
    
    ┌─────────────────────────────────────────────────────────┐
    │                   HYBRID STORE                          │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │    ┌─────────────────────────────────────┐              │
    │    │           CACHE LAYER               │              │
    │    │           (Redis)                   │              │
    │    │     • Hot data                      │              │
    │    │     • Fast reads                    │              │
    │    │     • TTL-based expiry              │              │
    │    └──────────────────┬──────────────────┘              │
    │                       │ miss                            │
    │                       ▼                                 │
    │    ┌─────────────────────────────────────┐              │
    │    │         PRIMARY STORE               │              │
    │    │         (PostgreSQL)                │              │
    │    │     • Persistent storage            │              │
    │    │     • Vector search                 │              │
    │    │     • ACID transactions             │              │
    │    └─────────────────────────────────────┘              │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class HybridStore(BaseStore):
        '''Cache layer over persistent store.'''
        
        def __init__(self, cache: BaseStore, primary: BaseStore):
            self.cache = cache
            self.primary = primary
            self.cache_ttl = 3600  # 1 hour
        
        async def get(self, key: str) -> Optional[Dict]:
            # Try cache first
            cached = await self.cache.get(key)
            if cached:
                return cached
            
            # Fall back to primary
            value = await self.primary.get(key)
            if value:
                # Populate cache
                await self.cache.put(key, value)
            return value
        
        async def put(self, key: str, value: Dict) -> None:
            # Write to both
            await self.primary.put(key, value)
            await self.cache.put(key, value)
        
        async def delete(self, key: str) -> None:
            # Delete from both
            await self.cache.delete(key)
            await self.primary.delete(key)
        
        async def search(self, query: str, limit: int = 10) -> List[Dict]:
            # Search always goes to primary (has vectors)
            results = await self.primary.search(query, limit)
            
            # Optionally cache top results
            for result in results[:3]:
                if 'key' in result:
                    await self.cache.put(result['key'], result)
            
            return results
    """)


# =============================================================================
# STORE-SPECIFIC CONFIGURATIONS
# =============================================================================


def demo_store_configs():
    """Show how to configure custom stores with LearningMachine."""

    print("\n" + "=" * 60)
    print("CUSTOM STORE CONFIGURATION")
    print("=" * 60)

    print("""
    Configure LearningMachine to use custom stores:
    """)

    print("\n💻 CONFIGURATION:")
    print("-" * 40)
    print("""
    from agno.learn import LearningMachine, LearningMode
    from agno.learn.config import (
        UserProfileConfig,
        EntityMemoryConfig,
        LearnedKnowledgeConfig
    )
    
    # Initialize custom stores
    user_store = PostgresStore(
        connection_string="postgresql://...",
        table="user_profiles"
    )
    
    entity_store = HybridStore(
        cache=RedisStore(url="redis://..."),
        primary=PostgresStore(
            connection_string="postgresql://...",
            table="entities"
        )
    )
    
    knowledge_store = PostgresStore(
        connection_string="postgresql://...",
        table="learned_knowledge"
    )
    
    # Configure machine with custom stores
    machine = LearningMachine(
        user_profile=UserProfileConfig(
            store=user_store
        ),
        entity_memory=EntityMemoryConfig(
            store=entity_store,
            namespace="default"
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            store=knowledge_store,
            namespace="default"
        ),
        user_id="user123",
        session_id="session456"
    )
    """)


# =============================================================================
# MIGRATION STRATEGIES
# =============================================================================


def demo_migration():
    """Show migration strategies between stores."""

    print("\n" + "=" * 60)
    print("MIGRATION STRATEGIES")
    print("=" * 60)

    print("""
    Migrating from one store to another:
    
    ┌─────────────────────────────────────────────────────────┐
    │              MIGRATION APPROACHES                       │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  1. OFFLINE MIGRATION:                                  │
    │     • Stop writes                                       │
    │     • Copy all data                                     │
    │     • Switch to new store                               │
    │     • Resume writes                                     │
    │     → Best for: Small datasets, scheduled maintenance   │
    │                                                         │
    │  2. DUAL WRITE:                                         │
    │     • Write to both stores simultaneously               │
    │     • Read from old store                               │
    │     • Background copy historical data                   │
    │     • Switch reads to new store                         │
    │     • Stop writes to old store                          │
    │     → Best for: Zero downtime, large datasets           │
    │                                                         │
    │  3. LAZY MIGRATION:                                     │
    │     • Read from new, fall back to old                   │
    │     • Write only to new                                 │
    │     • Copy on read from old                             │
    │     • Eventually all data migrated                      │
    │     → Best for: Gradual transition, read-heavy          │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 DUAL WRITE EXAMPLE:")
    print("-" * 40)
    print("""
    class MigrationStore(BaseStore):
        '''Dual-write store for migrations.'''
        
        def __init__(
            self, 
            old_store: BaseStore, 
            new_store: BaseStore,
            read_from: str = "old"  # "old", "new", or "both"
        ):
            self.old = old_store
            self.new = new_store
            self.read_from = read_from
        
        async def get(self, key: str) -> Optional[Dict]:
            if self.read_from == "new":
                return await self.new.get(key)
            elif self.read_from == "old":
                return await self.old.get(key)
            else:  # "both" - try new first, fall back to old
                value = await self.new.get(key)
                if value is None:
                    value = await self.old.get(key)
                    if value:
                        # Copy to new store
                        await self.new.put(key, value)
                return value
        
        async def put(self, key: str, value: Dict) -> None:
            # Always write to both during migration
            await asyncio.gather(
                self.old.put(key, value),
                self.new.put(key, value)
            )
        
        def switch_reads_to_new(self):
            '''Call when migration complete.'''
            self.read_from = "new"
        
        def finish_migration(self):
            '''Return new store only.'''
            return self.new
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("🗄️ CUSTOM STORE IMPLEMENTATION")
    print("=" * 60)
    print("Building custom storage backends")
    print()

    demo_store_interface()
    demo_postgres_store()
    demo_redis_store()
    demo_hybrid_store()
    demo_store_configs()
    demo_migration()

    print("\n" + "=" * 60)
    print("✅ Custom store guide complete!")
    print("=" * 60)
