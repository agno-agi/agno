"""
Debugging Learning Systems
==========================

Tools and techniques for debugging learning system issues.

Key Concepts:
- Inspecting stored data
- Tracing extraction
- Common issues and fixes
- Testing strategies

Run: python -m cookbook.advanced.06_debugging
"""

from datetime import datetime

from langmem import create_learning_machine

# =============================================================================
# INSPECTING STORED DATA
# =============================================================================


def demo_inspect_data():
    """Show how to inspect what's stored."""

    print("=" * 60)
    print("INSPECTING STORED DATA")
    print("=" * 60)

    print("""
    Debug by examining what's actually stored:
    """)

    print("\n💻 INSPECTION UTILITIES:")
    print("-" * 40)
    print("""
    class LearningDebugger:
        '''Utilities for debugging learning stores.'''
        
        def __init__(self, machine):
            self.machine = machine
        
        async def dump_user_profile(self, user_id: str):
            '''Print all facts for a user.'''
            profile = await self.machine.user_profile_store.get(user_id)
            
            print(f"\\n=== User Profile: {user_id} ===")
            if not profile:
                print("  (empty)")
                return
            
            for fact in profile.get("facts", []):
                print(f"  • {fact['key']}: {fact['value']}")
                print(f"    confidence: {fact.get('confidence', 'N/A')}")
                print(f"    updated: {fact.get('updated_at', 'N/A')}")
        
        async def dump_entities(self, namespace: str, limit: int = 20):
            '''Print entities in a namespace.'''
            entities = await self.machine.entity_store.list(
                prefix=namespace,
                limit=limit
            )
            
            print(f"\\n=== Entities: {namespace} ===")
            for entity in entities:
                print(f"  [{entity['type']}] {entity['name']}")
                print(f"    facts: {len(entity.get('facts', []))}")
                print(f"    relationships: {len(entity.get('relationships', []))}")
        
        async def dump_knowledge(self, namespace: str, limit: int = 10):
            '''Print learned knowledge.'''
            knowledge = await self.machine.knowledge_store.list(
                prefix=namespace,
                limit=limit
            )
            
            print(f"\\n=== Learned Knowledge: {namespace} ===")
            for item in knowledge:
                print(f"  • {item['content'][:100]}...")
                print(f"    confidence: {item.get('confidence', 'N/A')}")
                print(f"    applied: {item.get('application_count', 0)} times")
        
        async def search_debug(self, query: str, store: str = "all"):
            '''Search and show what would be retrieved.'''
            print(f"\\n=== Search: '{query}' ===")
            
            if store in ["all", "entities"]:
                entities = await self.machine.entity_store.search(query)
                print(f"\\nEntities ({len(entities)} results):")
                for e in entities[:5]:
                    print(f"  • {e['name']} (score: {e.get('score', 'N/A')})")
            
            if store in ["all", "knowledge"]:
                knowledge = await self.machine.knowledge_store.search(query)
                print(f"\\nKnowledge ({len(knowledge)} results):")
                for k in knowledge[:5]:
                    print(f"  • {k['content'][:60]}... (score: {k.get('score', 'N/A')})")
    """)


# =============================================================================
# TRACING EXTRACTION
# =============================================================================


def demo_trace_extraction():
    """Show how to trace extraction process."""

    print("\n" + "=" * 60)
    print("TRACING EXTRACTION")
    print("=" * 60)

    print("""
    Trace what the extraction model produces:
    """)

    print("\n💻 EXTRACTION TRACER:")
    print("-" * 40)
    print("""
    class ExtractionTracer:
        '''Trace extraction for debugging.'''
        
        def __init__(self, machine, verbose: bool = True):
            self.machine = machine
            self.verbose = verbose
            self.traces = []
        
        async def traced_extract(self, messages: List[Dict]):
            '''Run extraction with full tracing.'''
            
            trace = {
                "timestamp": datetime.now().isoformat(),
                "input_messages": len(messages),
                "extractions": {}
            }
            
            # Capture raw extraction output
            for store_name in ["user_profile", "entity_memory", "learned_knowledge"]:
                store = getattr(self.machine, f"{store_name}_extractor", None)
                if not store:
                    continue
                
                # Get raw extraction before storage
                raw_output = await store.extract_raw(messages)
                
                trace["extractions"][store_name] = {
                    "raw_output": raw_output,
                    "items_extracted": len(raw_output.get("items", [])),
                    "tokens_used": raw_output.get("usage", {})
                }
                
                if self.verbose:
                    print(f"\\n=== {store_name} extraction ===")
                    print(f"Items: {len(raw_output.get('items', []))}")
                    for item in raw_output.get("items", []):
                        print(f"  • {item}")
            
            self.traces.append(trace)
            return trace
        
        def export_traces(self, path: str):
            '''Export traces for analysis.'''
            import json
            with open(path, 'w') as f:
                json.dump(self.traces, f, indent=2)
    """)


# =============================================================================
# COMMON ISSUES
# =============================================================================


def demo_common_issues():
    """Show common issues and their fixes."""

    print("\n" + "=" * 60)
    print("COMMON ISSUES AND FIXES")
    print("=" * 60)

    print("""
    ┌─────────────────────────────────────────────────────────┐
    │  ISSUE: Nothing being extracted                         │
    ├─────────────────────────────────────────────────────────┤
    │  Symptoms:                                              │
    │  • Stores remain empty after conversations              │
    │  • No errors, just no data                              │
    │                                                         │
    │  Causes:                                                │
    │  • Extraction mode set to manual (HITL)                 │
    │  • Messages too short to trigger extraction             │
    │  • Wrong message format                                 │
    │                                                         │
    │  Fixes:                                                 │
    │  • Check learning_mode config                           │
    │  • Verify message format: {"role": "...", "content": }  │
    │  • Add more conversational content                      │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  ISSUE: Wrong data being extracted                      │
    ├─────────────────────────────────────────────────────────┤
    │  Symptoms:                                              │
    │  • Extracted facts don't match conversation             │
    │  • Entities have wrong types                            │
    │  • Relationships are incorrect                          │
    │                                                         │
    │  Causes:                                                │
    │  • Ambiguous conversation context                       │
    │  • Schema too permissive                                │
    │  • Extraction prompt needs tuning                       │
    │                                                         │
    │  Fixes:                                                 │
    │  • Use custom schema with clear types                   │
    │  • Add examples to extraction prompt                    │
    │  • Use PROPOSE mode to review before saving             │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  ISSUE: Duplicate entities                              │
    ├─────────────────────────────────────────────────────────┤
    │  Symptoms:                                              │
    │  • Same entity stored multiple times                    │
    │  • "John Smith" and "John" as separate entities         │
    │                                                         │
    │  Causes:                                                │
    │  • Different name variations                            │
    │  • No deduplication logic                               │
    │                                                         │
    │  Fixes:                                                 │
    │  • Enable entity resolution in config                   │
    │  • Add name normalization                               │
    │  • Run periodic deduplication                           │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │  ISSUE: Context not being used                          │
    ├─────────────────────────────────────────────────────────┤
    │  Symptoms:                                              │
    │  • Agent doesn't use stored information                 │
    │  • Personalization not appearing in responses           │
    │                                                         │
    │  Causes:                                                │
    │  • Context retrieval failing silently                   │
    │  • Retrieved context not injected into prompt           │
    │  • Search returning wrong results                       │
    │                                                         │
    │  Fixes:                                                 │
    │  • Debug search with test queries                       │
    │  • Verify context injection in prompt template          │
    │  • Check embedding quality                              │
    └─────────────────────────────────────────────────────────┘
    """)


# =============================================================================
# DEBUG CONFIGURATION
# =============================================================================


def demo_debug_config():
    """Show debug-friendly configuration."""

    print("\n" + "=" * 60)
    print("DEBUG CONFIGURATION")
    print("=" * 60)

    print("""
    Configure for maximum visibility during development:
    """)

    print("\n💻 DEBUG SETUP:")
    print("-" * 40)
    print("""
    import logging
    
    # Enable detailed logging
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("langmem").setLevel(logging.DEBUG)
    
    # Create machine with debug options
    machine = create_learning_machine(
        user_profile={
            "enabled": True,
            "debug": True,  # Log all extractions
        },
        entity_memory={
            "namespace": "debug",
            "debug": True,
        },
        learned_knowledge={
            "namespace": "debug",
            "mode": "propose",  # Review before saving
            "debug": True,
        },
        user_id="debug_user",
        session_id="debug_session",
        
        # Global debug options
        verbose=True,
        log_extractions=True,
        log_retrievals=True,
    )
    
    # Add callback for inspection
    def on_extraction(store, items):
        print(f"[DEBUG] Extracted to {store}: {len(items)} items")
        for item in items:
            print(f"  {item}")
    
    machine.on_extraction = on_extraction
    """)


# =============================================================================
# TESTING STRATEGIES
# =============================================================================


def demo_testing():
    """Show testing strategies for learning systems."""

    print("\n" + "=" * 60)
    print("TESTING STRATEGIES")
    print("=" * 60)

    print("""
    Test learning systems effectively:
    """)

    print("\n💻 UNIT TESTS:")
    print("-" * 40)
    print("""
    import pytest
    from unittest.mock import AsyncMock
    
    @pytest.fixture
    def mock_store():
        '''Create mock store for testing.'''
        store = AsyncMock()
        store.get.return_value = None
        store.search.return_value = []
        return store
    
    @pytest.fixture
    def test_machine(mock_store):
        '''Create machine with mock stores.'''
        return create_learning_machine(
            user_profile={"store": mock_store},
            entity_memory={"store": mock_store},
            user_id="test_user"
        )
    
    @pytest.mark.asyncio
    async def test_extraction_called(test_machine, mock_store):
        '''Verify extraction happens on invoke.'''
        messages = [
            {"role": "user", "content": "My name is Alice"}
        ]
        
        await test_machine.ainvoke({"messages": messages})
        
        # Verify store was called
        assert mock_store.put.called
    """)

    print("\n💻 INTEGRATION TESTS:")
    print("-" * 40)
    print("""
    @pytest.mark.asyncio
    async def test_user_profile_extraction():
        '''Test actual extraction with real store.'''
        machine = create_learning_machine(
            user_profile=True,
            user_id="integration_test_user"
        )
        
        # Conversation with extractable info
        messages = [
            {"role": "user", "content": "Hi, I'm a software engineer at Google"},
            {"role": "assistant", "content": "Nice to meet you!"},
            {"role": "user", "content": "I mainly work with Python and Go"}
        ]
        
        await machine.ainvoke({"messages": messages})
        
        # Verify extraction
        profile = await machine.user_profile_store.get("integration_test_user")
        
        assert profile is not None
        assert any("engineer" in str(f).lower() for f in profile.get("facts", []))
        assert any("google" in str(f).lower() for f in profile.get("facts", []))
    """)

    print("\n💻 GOLDEN TESTS:")
    print("-" * 40)
    print("""
    # test_golden_extractions.py
    
    GOLDEN_CASES = [
        {
            "name": "basic_user_info",
            "messages": [
                {"role": "user", "content": "I'm Alice, a PM at Stripe"}
            ],
            "expected_facts": [
                {"key": "name", "value": "Alice"},
                {"key": "role", "value": "PM"},
                {"key": "company", "value": "Stripe"}
            ]
        },
        {
            "name": "preferences",
            "messages": [
                {"role": "user", "content": "I prefer dark mode and vim keybindings"}
            ],
            "expected_facts": [
                {"key": "theme_preference", "value": "dark mode"},
                {"key": "editor_preference", "value": "vim keybindings"}
            ]
        }
    ]
    
    @pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["name"])
    @pytest.mark.asyncio
    async def test_golden_extraction(case, test_machine):
        '''Test extraction against golden examples.'''
        await test_machine.ainvoke({"messages": case["messages"]})
        
        profile = await test_machine.get_user_profile()
        
        for expected in case["expected_facts"]:
            assert any(
                f["key"] == expected["key"] and 
                expected["value"].lower() in f["value"].lower()
                for f in profile["facts"]
            ), f"Missing: {expected}"
    """)


# =============================================================================
# LOGGING SETUP
# =============================================================================


def demo_logging():
    """Show logging configuration."""

    print("\n" + "=" * 60)
    print("LOGGING CONFIGURATION")
    print("=" * 60)

    print("""
    Structured logging for production debugging:
    """)

    print("\n💻 LOGGING SETUP:")
    print("-" * 40)
    print("""
    import logging
    import structlog
    
    # Configure structlog for structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    logger = structlog.get_logger("langmem")
    
    # Log extraction events
    logger.info(
        "extraction_complete",
        user_id="user123",
        store="user_profile",
        items_extracted=5,
        duration_ms=234,
        conversation_length=12
    )
    
    # Log retrieval events
    logger.info(
        "context_retrieved",
        user_id="user123",
        query="python debugging",
        entities_found=3,
        knowledge_found=2,
        duration_ms=45
    )
    
    # Log errors with context
    logger.error(
        "extraction_failed",
        user_id="user123",
        error_type="timeout",
        messages_count=50,
        exc_info=True
    )
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("🔍 DEBUGGING LEARNING SYSTEMS")
    print("=" * 60)
    print("Tools and techniques for debugging")
    print()

    demo_inspect_data()
    demo_trace_extraction()
    demo_common_issues()
    demo_debug_config()
    demo_testing()
    demo_logging()

    print("\n" + "=" * 60)
    print("✅ Debugging guide complete!")
    print("=" * 60)
