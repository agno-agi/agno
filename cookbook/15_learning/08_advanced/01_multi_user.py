"""
Multi-User Learning
===================

Managing learning across multiple users, including shared knowledge,
user isolation, and team collaboration patterns.

Key Concepts:
- User isolation for privacy
- Shared namespaces for team knowledge
- Cross-user pattern extraction
- Multi-tenant architectures

Run: python -m cookbook.advanced.01_multi_user
"""

from agno.learn import LearningMachine

# =============================================================================
# USER ISOLATION
# =============================================================================


def demo_user_isolation():
    """Show how user data is isolated by default."""

    print("=" * 60)
    print("USER ISOLATION DEMO")
    print("=" * 60)

    print("""
    By default, each user's data is completely isolated:
    
    ┌─────────────────┐     ┌─────────────────┐
    │     User A      │     │     User B      │
    ├─────────────────┤     ├─────────────────┤
    │ user_profile:   │     │ user_profile:   │
    │   name: Alice   │     │   name: Bob     │
    │   role: PM      │     │   role: Eng     │
    ├─────────────────┤     ├─────────────────┤
    │ session_context │     │ session_context │
    │   (Alice only)  │     │   (Bob only)    │
    ├─────────────────┤     ├─────────────────┤
    │ entity_memory   │     │ entity_memory   │
    │   namespace:    │     │   namespace:    │
    │   user:alice    │     │   user:bob      │
    └─────────────────┘     └─────────────────┘
    """)

    # Create isolated machines for two users
    alice_machine = LearningMachine(
        user_profile=True,
        session_context=True,
        entity_memory={
            "namespace": "user:alice"  # Alice's private namespace
        },
        user_id="alice",
        session_id="alice-session-1",
    )

    bob_machine = LearningMachine(
        user_profile=True,
        session_context=True,
        entity_memory={
            "namespace": "user:bob"  # Bob's private namespace
        },
        user_id="bob",
        session_id="bob-session-1",
    )

    print("✅ Created isolated machines for Alice and Bob")
    print("   - Each has their own user_profile (via user_id)")
    print("   - Each has their own entity namespace")
    print("   - Session contexts are separate")


# =============================================================================
# SHARED TEAM KNOWLEDGE
# =============================================================================


def demo_shared_knowledge():
    """Show team-shared knowledge patterns."""

    print("\n" + "=" * 60)
    print("SHARED TEAM KNOWLEDGE DEMO")
    print("=" * 60)

    print("""
    Teams can share knowledge while keeping profiles private:
    
    ┌─────────────────────────────────────────────────────────┐
    │                   TEAM: Engineering                     │
    ├─────────────────────────────────────────────────────────┤
    │  SHARED (team namespace):                               │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │ entity_memory: "team:engineering"                │   │
    │  │   - Project entities                             │   │
    │  │   - Codebase knowledge                           │   │
    │  │   - Team decisions                               │   │
    │  ├─────────────────────────────────────────────────┤   │
    │  │ learned_knowledge: "team:engineering"            │   │
    │  │   - Coding patterns                              │   │
    │  │   - Best practices                               │   │
    │  │   - Common solutions                             │   │
    │  └─────────────────────────────────────────────────┘   │
    │                                                         │
    │  PRIVATE (per user):                                    │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
    │  │ Alice        │  │ Bob          │  │ Carol        │  │
    │  │ user_profile │  │ user_profile │  │ user_profile │  │
    │  │ preferences  │  │ preferences  │  │ preferences  │  │
    │  └──────────────┘  └──────────────┘  └──────────────┘  │
    └─────────────────────────────────────────────────────────┘
    """)

    def create_team_member_machine(user_id: str, team: str):
        """Create machine with private profile + shared team knowledge."""
        return LearningMachine(
            # Private per user
            user_profile=True,
            # Shared across team
            entity_memory={"namespace": f"team:{team}"},
            learned_knowledge={"namespace": f"team:{team}"},
            user_id=user_id,
            session_id=f"{user_id}-session",
        )

    # All team members share entity and learned knowledge
    alice = create_team_member_machine("alice", "engineering")
    bob = create_team_member_machine("bob", "engineering")
    carol = create_team_member_machine("carol", "engineering")

    print("✅ Created 3 team members with:")
    print("   - Private: user_profile (preferences, communication style)")
    print("   - Shared: entity_memory (projects, codebases)")
    print("   - Shared: learned_knowledge (patterns, practices)")


# =============================================================================
# HIERARCHICAL NAMESPACES
# =============================================================================


def demo_hierarchical_namespaces():
    """Show hierarchical namespace patterns."""

    print("\n" + "=" * 60)
    print("HIERARCHICAL NAMESPACES DEMO")
    print("=" * 60)

    print("""
    Organizations can use hierarchical namespaces:
    
    ┌─────────────────────────────────────────────────────────┐
    │                      GLOBAL                             │
    │                 "global:company"                        │
    │           (company-wide knowledge)                      │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │    ┌─────────────────┐     ┌─────────────────┐         │
    │    │   DEPARTMENT    │     │   DEPARTMENT    │         │
    │    │ "dept:eng"      │     │ "dept:sales"    │         │
    │    └────────┬────────┘     └────────┬────────┘         │
    │             │                       │                   │
    │    ┌────────┴────────┐     ┌────────┴────────┐         │
    │    │                 │     │                 │         │
    │ ┌──┴───┐  ┌──────┐  │  ┌──┴───┐  ┌──────┐   │         │
    │ │TEAM  │  │TEAM  │  │  │TEAM  │  │TEAM  │   │         │
    │ │front │  │back  │  │  │ west │  │ east │   │         │
    │ └──────┘  └──────┘  │  └──────┘  └──────┘   │         │
    │                     │                       │         │
    └─────────────────────────────────────────────────────────┘
    """)

    def create_hierarchical_machine(user_id: str, team: str, department: str):
        """Create machine that reads from multiple namespace levels."""

        # Primary namespace is team level
        # But can search across hierarchy
        return LearningMachine(
            user_profile=True,
            entity_memory={"namespace": f"team:{team}"},
            learned_knowledge={
                "namespace": f"team:{team}"
                # Note: Search can span namespaces via application logic
            },
            user_id=user_id,
            session_id=f"{user_id}-session",
        )

    # Example usage
    frontend_dev = create_hierarchical_machine(
        user_id="alice", team="frontend", department="engineering"
    )

    print("✅ Hierarchical namespace pattern:")
    print("   - Write to: team:frontend")
    print("   - Read from: team:frontend + dept:eng + global")
    print("   - Knowledge bubbles up, stays scoped down")


# =============================================================================
# CROSS-USER PATTERNS
# =============================================================================


def demo_cross_user_patterns():
    """Show extracting patterns across users."""

    print("\n" + "=" * 60)
    print("CROSS-USER PATTERN EXTRACTION DEMO")
    print("=" * 60)

    print("""
    Extract patterns from many users into shared knowledge:
    
    ┌─────────────────────────────────────────────────────────┐
    │              INDIVIDUAL SESSIONS                        │
    │                                                         │
    │   User A: "I solved the auth bug by checking tokens"    │
    │   User B: "Token validation fixed my login issue"       │
    │   User C: "Auth problems? Check token expiry"           │
    │                                                         │
    └───────────────────────┬─────────────────────────────────┘
                            │ Pattern Extraction
                            ▼
    ┌─────────────────────────────────────────────────────────┐
    │              SHARED KNOWLEDGE                           │
    │                                                         │
    │   Pattern: "Authentication issues are commonly          │
    │   resolved by validating token expiry and refresh       │
    │   logic. Check: 1) Token expiry times 2) Refresh        │
    │   token flow 3) Clock synchronization"                  │
    │                                                         │
    │   Confidence: High (3 users, similar solutions)         │
    │   Namespace: global:troubleshooting                     │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("💡 IMPLEMENTATION APPROACH:")
    print("-" * 40)
    print("""
    1. COLLECT: Each user's learned_knowledge in private namespace
    
    2. AGGREGATE: Periodic job scans private namespaces
       - Find similar patterns across users
       - Verify patterns occur multiple times
       - Anonymize user-specific details
    
    3. PROMOTE: Validated patterns go to shared namespace
       - global:troubleshooting
       - global:best_practices
       - team:{name}:patterns
    
    4. CURATE: Human review before promotion (optional)
       - Ensure quality
       - Remove sensitive info
       - Refine wording
    """)


# =============================================================================
# MULTI-TENANT ARCHITECTURE
# =============================================================================


def demo_multi_tenant():
    """Show multi-tenant architecture patterns."""

    print("\n" + "=" * 60)
    print("MULTI-TENANT ARCHITECTURE DEMO")
    print("=" * 60)

    print("""
    SaaS applications serving multiple organizations:
    
    ┌─────────────────────────────────────────────────────────┐
    │                    TENANT: Acme Corp                    │
    ├─────────────────────────────────────────────────────────┤
    │  namespace prefix: "tenant:acme:"                       │
    │                                                         │
    │  Users:                                                 │
    │    user_id: "acme:alice"                                │
    │    user_id: "acme:bob"                                  │
    │                                                         │
    │  Entities:                                              │
    │    namespace: "tenant:acme:entities"                    │
    │                                                         │
    │  Knowledge:                                             │
    │    namespace: "tenant:acme:knowledge"                   │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │                    TENANT: Globex Inc                   │
    ├─────────────────────────────────────────────────────────┤
    │  namespace prefix: "tenant:globex:"                     │
    │                                                         │
    │  Users:                                                 │
    │    user_id: "globex:charlie"                            │
    │    user_id: "globex:diana"                              │
    │                                                         │
    │  Entities:                                              │
    │    namespace: "tenant:globex:entities"                  │
    │                                                         │
    │  Knowledge:                                             │
    │    namespace: "tenant:globex:knowledge"                 │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    def create_tenant_machine(tenant_id: str, user_id: str):
        """Create machine scoped to a tenant."""

        # Prefix everything with tenant
        scoped_user_id = f"{tenant_id}:{user_id}"

        return LearningMachine(
            user_profile=True,
            session_context=True,
            entity_memory={"namespace": f"tenant:{tenant_id}:entities"},
            learned_knowledge={"namespace": f"tenant:{tenant_id}:knowledge"},
            user_id=scoped_user_id,
            session_id=f"{scoped_user_id}-session",
        )

    # Acme users
    acme_alice = create_tenant_machine("acme", "alice")
    acme_bob = create_tenant_machine("acme", "bob")

    # Globex users
    globex_charlie = create_tenant_machine("globex", "charlie")

    print("✅ Multi-tenant isolation:")
    print("   - Acme users can't see Globex data")
    print("   - Each tenant has isolated namespaces")
    print("   - user_id prefixed for global uniqueness")


# =============================================================================
# BEST PRACTICES
# =============================================================================


def show_best_practices():
    """Display multi-user best practices."""

    print("\n" + "=" * 60)
    print("MULTI-USER BEST PRACTICES")
    print("=" * 60)

    print("""
    ✅ ISOLATION:
    
    1. Always scope user_id uniquely
       - Bad:  user_id="alice"
       - Good: user_id="tenant:acme:alice"
    
    2. Use explicit namespaces for shared data
       - Private: "user:{user_id}"
       - Team: "team:{team_id}"
       - Tenant: "tenant:{tenant_id}"
    
    3. Never assume isolation - verify
       - Test that User A can't see User B's data
       - Test namespace boundaries
    
    ✅ SHARING:
    
    1. Be explicit about what's shared
       - Document namespace purposes
       - Make sharing opt-in where possible
    
    2. Consider privacy implications
       - User profiles should rarely be shared
       - Anonymize cross-user patterns
    
    3. Use hierarchical namespaces thoughtfully
       - Global < Org < Dept < Team < User
       - Knowledge flows up, access flows down
    
    ✅ SCALE:
    
    1. Plan namespace strategy early
       - Changing later is expensive
       - Consider multi-tenant from start
    
    2. Monitor namespace growth
       - Set quotas per user/team
       - Archive old data
    
    3. Index strategically
       - High-traffic namespaces need attention
       - Consider read replicas for shared knowledge
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("👥 MULTI-USER LEARNING")
    print("=" * 60)
    print("Patterns for multiple users, teams, and tenants")
    print()

    demo_user_isolation()
    demo_shared_knowledge()
    demo_hierarchical_namespaces()
    demo_cross_user_patterns()
    demo_multi_tenant()
    show_best_practices()

    print("\n" + "=" * 60)
    print("✅ Multi-user patterns complete!")
    print("=" * 60)
