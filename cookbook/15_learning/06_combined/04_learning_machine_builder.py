"""
Combined Learning: Learning Machine Builder Patterns

Different ways to construct and configure a LearningMachine. Shows
factory patterns, builder approaches, and configuration management
for different deployment scenarios.

Key concepts:
- Configuration objects vs boolean shortcuts
- Factory functions for common patterns
- Environment-based configuration
- Testing and development setups

Run: python -m cookbook.combined.04_learning_machine_builder
"""

import os
from dataclasses import dataclass
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat

# Database URL - use environment variable in production
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# BOOLEAN SHORTCUTS vs CONFIGURATION OBJECTS
# =============================================================================


def demo_boolean_shortcuts():
    """Simplest way to enable learning stores."""
    print("\n" + "=" * 60)
    print("BOOLEAN SHORTCUTS")
    print("=" * 60)

    # Simplest: just enable with True
    simple_learning = LearningMachine(
        db=db,
        user_profile=True,  # Enable with defaults
        session_context=True,  # Enable with defaults
    )

    # Or even simpler on the agent
    simple_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=True,  # Enable all defaults
        user_id="user_123",
        session_id="session_456",
    )

    print("""
    Boolean shortcuts use sensible defaults:

    learning=True
    ├── user_profile: enabled (ALWAYS mode)
    ├── session_context: enabled (planning disabled)
    ├── entity_memory: disabled
    └── learned_knowledge: disabled


    LearningMachine(user_profile=True, session_context=True)
    ├── user_profile: ALWAYS mode, default schema
    └── session_context: planning disabled
    
    
    Use booleans when:
    ✓ Getting started quickly
    ✓ Default behavior is acceptable
    ✓ Simple use cases
    """)


def demo_configuration_objects():
    """Full control with configuration objects."""
    print("\n" + "=" * 60)
    print("CONFIGURATION OBJECTS")
    print("=" * 60)

    # Full control with config objects
    configured_learning = LearningMachine(
        db=db,
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
            # custom_schema=MyCustomProfile,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="user:123",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,
            namespace="team:engineering",
        ),
    )

    print("""
    Configuration objects give full control:
    
    UserProfileConfig:
    - mode: ALWAYS or AGENTIC
    - custom_schema: Your dataclass (optional)

    SessionContextConfig:
    - enable_planning: Include goal/plan/progress

    EntityMemoryConfig:
    - mode: ALWAYS or AGENTIC
    - namespace: Scoping for isolation

    LearnedKnowledgeConfig:
    - mode: AGENTIC, PROPOSE, or ALWAYS
    - namespace: Scoping for isolation
    
    
    Use config objects when:
    ✓ Need non-default modes
    ✓ Custom schemas
    ✓ Namespace scoping
    ✓ Fine-grained control
    """)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_personal_assistant_learning(user_id: str) -> LearningMachine:
    """Factory for personal assistant agents."""
    return LearningMachine(
        db=db,
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.ALWAYS,
            namespace=f"user:{user_id}",
        ),
    )


def create_support_agent_learning(user_id: str, org_id: str) -> LearningMachine:
    """Factory for support/help desk agents."""
    return LearningMachine(
        db=db,
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Track issue resolution
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.ALWAYS,
            namespace=f"org:{org_id}:support",  # Shared within org
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,  # Save solutions
            namespace=f"org:{org_id}:kb",
        ),
    )


def create_team_knowledge_learning(team: str) -> LearningMachine:
    """Factory for team knowledge agents."""
    return LearningMachine(
        db=db,
        session_context=SessionContextConfig(
            enable_planning=False,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace=f"team:{team}",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace=f"team:{team}",
        ),
    )


def demo_factory_functions():
    """Show factory function usage."""
    print("\n" + "=" * 60)
    print("FACTORY FUNCTIONS")
    print("=" * 60)

    print("""
    Factory functions encapsulate common configurations:
    
    
    # Personal assistant
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=create_personal_assistant_learning("user_123"),
        user_id="user_123",
        session_id="session_456",
    )
    
    # Support agent
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=create_support_agent_learning("user_123", "acme_corp"),
        user_id="user_123",
        session_id="ticket_789",
    )
    
    # Team knowledge agent
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=create_team_knowledge_learning("engineering"),
        session_id="query_123",
    )
    
    
    Benefits:
    ✓ Consistent configuration across agents
    ✓ Easy to update all agents at once
    ✓ Self-documenting use cases
    ✓ Reduces configuration errors
    """)


# =============================================================================
# ENVIRONMENT-BASED CONFIGURATION
# =============================================================================


@dataclass
class LearningConfig:
    """Configuration loaded from environment."""

    db_url: str
    default_mode: LearningMode
    enable_user_profile: bool
    enable_session_context: bool
    enable_entity_memory: bool
    enable_learned_knowledge: bool
    entity_namespace_prefix: str
    knowledge_namespace_prefix: str

    @classmethod
    def from_env(cls) -> "LearningConfig":
        """Load configuration from environment variables."""
        mode_str = os.getenv("LEARNING_MODE", "ALWAYS")
        mode = LearningMode[mode_str.upper()]

        return cls(
            db_url=os.getenv("DATABASE_URL", db_url),
            default_mode=mode,
            enable_user_profile=os.getenv("ENABLE_USER_PROFILE", "true").lower()
            == "true",
            enable_session_context=os.getenv("ENABLE_SESSION_CONTEXT", "true").lower()
            == "true",
            enable_entity_memory=os.getenv("ENABLE_ENTITY_MEMORY", "false").lower()
            == "true",
            enable_learned_knowledge=os.getenv(
                "ENABLE_LEARNED_KNOWLEDGE", "false"
            ).lower()
            == "true",
            entity_namespace_prefix=os.getenv("ENTITY_NAMESPACE_PREFIX", "user"),
            knowledge_namespace_prefix=os.getenv(
                "KNOWLEDGE_NAMESPACE_PREFIX", "global"
            ),
        )

    def create_learning_machine(
        self,
        user_id: Optional[str] = None,
    ) -> LearningMachine:
        """Create LearningMachine from this config."""
        return LearningMachine(
            db_url=self.db_url,
            user_profile=UserProfileConfig(
                mode=self.default_mode,
            )
            if self.enable_user_profile
            else False,
            session_context=SessionContextConfig(
                enable_planning=True,
            )
            if self.enable_session_context
            else False,
            entity_memory=EntityMemoryConfig(
                mode=self.default_mode,
                namespace=f"{self.entity_namespace_prefix}:{user_id}"
                if user_id
                else self.entity_namespace_prefix,
            )
            if self.enable_entity_memory
            else False,
            learned_knowledge=LearnedKnowledgeConfig(
                mode=self.default_mode,
                namespace=self.knowledge_namespace_prefix,
            )
            if self.enable_learned_knowledge
            else False,
        )


def demo_environment_config():
    """Show environment-based configuration."""
    print("\n" + "=" * 60)
    print("ENVIRONMENT-BASED CONFIGURATION")
    print("=" * 60)

    print("""
    Configure via environment variables:
    
    # .env file
    DATABASE_URL=postgresql+psycopg://...
    LEARNING_MODE=ALWAYS
    ENABLE_USER_PROFILE=true
    ENABLE_SESSION_CONTEXT=true
    ENABLE_ENTITY_MEMORY=true
    ENABLE_LEARNED_KNOWLEDGE=false
    ENTITY_NAMESPACE_PREFIX=user
    KNOWLEDGE_NAMESPACE_PREFIX=global
    
    
    # Usage
    config = LearningConfig.from_env()
    
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=config.create_learning_machine(user_id="user_123"),
        user_id="user_123",
        session_id="session_456",
    )
    
    
    Benefits:
    ✓ Different configs per environment (dev/staging/prod)
    ✓ No code changes for configuration
    ✓ Easy to enable/disable features
    ✓ Secrets stay out of code
    """)


# =============================================================================
# TESTING CONFIGURATIONS
# =============================================================================


def create_test_learning(
    enable_stores: bool = True,
    use_memory_db: bool = True,
) -> Optional[LearningMachine]:
    """Create learning configuration for tests."""
    if not enable_stores:
        return None

    # Use in-memory SQLite for fast tests
    test_db = "sqlite:///:memory:" if use_memory_db else db_url

    return LearningMachine(
        db_url=test_db,
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    )


def demo_testing_configs():
    """Show testing configuration approaches."""
    print("\n" + "=" * 60)
    print("TESTING CONFIGURATIONS")
    print("=" * 60)

    print("""
    Different test scenarios need different configs:
    
    
    UNIT TESTS (No learning):
    
        agent = Agent(
            model=MockModel(),
            learning=None,  # Disabled
        )
    
    
    INTEGRATION TESTS (In-memory DB):
    
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            learning=LearningMachine(
                db_url="sqlite:///:memory:",
                user_profile=True,
            ),
            user_id="test_user",
        )
    
    
    E2E TESTS (Real DB, isolated namespace):
    
        test_run_id = str(uuid.uuid4())
        
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            db=db,
            learning=LearningMachine(
                db=db,
                entity_memory=EntityMemoryConfig(
                    namespace=f"test:{test_run_id}",  # Isolated
                ),
            ),
            user_id=f"test_user_{test_run_id}",
        )
        
        # Cleanup after test
        # delete_namespace(f"test:{test_run_id}")
    
    
    FIXTURE APPROACH:
    
        @pytest.fixture
        def learning_agent():
            agent = Agent(
                model=OpenAIChat(id="gpt-4o"),
                learning=create_test_learning(),
                user_id="fixture_user",
                session_id="fixture_session",
            )
            yield agent
            # Cleanup handled by fixture
    """)


# =============================================================================
# PROGRESSIVE ENHANCEMENT
# =============================================================================


def demo_progressive_enhancement():
    """Show how to add learning incrementally."""
    print("\n" + "=" * 60)
    print("PROGRESSIVE ENHANCEMENT")
    print("=" * 60)

    print("""
    Start minimal, add learning stores as needed:
    
    
    PHASE 1: No Learning (Stateless)
    
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            # No learning parameter
        )
    
    
    PHASE 2: Add Session Context (Conversation tracking)

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            db=db,
            learning=LearningMachine(
                db=db,
                session_context=True,
            ),
            session_id="session_123",
        )


    PHASE 3: Add User Profile (Personalization)

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            db=db,
            learning=LearningMachine(
                db=db,
                user_profile=True,
                session_context=True,
            ),
            user_id="user_123",
            session_id="session_456",
        )


    PHASE 4: Add Entity Memory (Relationship tracking)

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            db=db,
            learning=LearningMachine(
                db=db,
                user_profile=True,
                session_context=True,
                entity_memory=EntityMemoryConfig(
                    namespace="user:123",
                ),
            ),
            user_id="user_123",
            session_id="session_456",
        )
    
    
    PHASE 5: Add Learned Knowledge (Organizational learning)
    
        # Full setup - see 03_full_learning_machine.py
    
    
    Each phase adds value independently.
    No need to implement all at once.
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("LEARNING MACHINE BUILDER PATTERNS")
    print("=" * 60)

    # Basic approaches
    demo_boolean_shortcuts()
    demo_configuration_objects()

    # Factory patterns
    demo_factory_functions()

    # Environment config
    demo_environment_config()

    # Testing
    demo_testing_configs()

    # Progressive enhancement
    demo_progressive_enhancement()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Multiple ways to configure LearningMachine:
    
    1. BOOLEAN SHORTCUTS
       Quick start with defaults
       learning=True or user_profile=True
    
    2. CONFIGURATION OBJECTS
       Full control with config classes
       UserProfileConfig, EntityMemoryConfig, etc.
    
    3. FACTORY FUNCTIONS
       Encapsulate common patterns
       create_personal_assistant_learning()
    
    4. ENVIRONMENT CONFIG
       Load from env vars
       Different configs per environment
    
    5. TEST CONFIGS
       In-memory DBs, isolated namespaces
       Easy cleanup between tests
    
    Start simple, enhance progressively.
    """)
