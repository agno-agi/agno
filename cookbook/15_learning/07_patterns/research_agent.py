"""
Pattern: Research Agent with Learning

A research assistant that learns from research sessions to become
more effective at finding, organizing, and synthesizing information.

Features:
- Remembers user's research interests and style
- Tracks research sessions and findings
- Builds knowledge of sources, papers, concepts
- Learns effective research patterns

Run: python -m cookbook.patterns.research_agent
"""

from agno.agent import Agent
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from cookbook.db import db_url

# =============================================================================
# RESEARCH AGENT CONFIGURATION
# =============================================================================


def create_research_agent(
    researcher_id: str,
    session_id: str,
    research_domain: str = "general",
) -> Agent:
    """
    Create a research agent with learning capabilities.

    Learning setup:
    - User profile: Researcher's interests, expertise, preferences
    - Session context: Current research question and progress
    - Entity memory: Papers, authors, concepts, sources
    - Learned knowledge: Research patterns, methodologies
    """
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        description="Research assistant specializing in literature review and synthesis",
        instructions=[
            "Understand the research question thoroughly before searching",
            "Track sources and maintain proper attribution",
            "Identify key papers, authors, and concepts",
            "Synthesize findings into coherent insights",
            "Note gaps in the literature for future exploration",
            "Save useful research patterns and methodologies",
        ],
        learning=LearningMachine(
            db_url=db_url,
            # Researcher profile
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # Research session tracking
            session_context=SessionContextConfig(
                enable_planning=True,  # Track research plan
            ),
            # Research entities (papers, authors, concepts)
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,  # Auto-extract from discussions
                namespace=f"research:{researcher_id}:{research_domain}",
            ),
            # Research methodologies and patterns
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"research:{research_domain}",  # Domain-shared
            ),
        ),
        user_id=researcher_id,
        session_id=session_id,
        markdown=True,
    )


# =============================================================================
# USAGE EXAMPLE
# =============================================================================


def demo_research_session():
    """Demonstrate a research session."""
    print("\n" + "=" * 60)
    print("RESEARCH SESSION DEMO")
    print("=" * 60)

    agent = create_research_agent(
        researcher_id="researcher_123",
        session_id="lit_review_456",
        research_domain="machine_learning",
    )

    print("""
    Scenario: Literature review on transformer architectures
    
    TURN 1:
    Researcher: "I need to do a literature review on attention 
                mechanisms in transformers, focusing on efficiency
                improvements since the original 2017 paper."
    
    Agent processes:
    
    1. SESSION CONTEXT captures:
       - Goal: "Literature review on efficient attention mechanisms"
       - Plan: "1. Start with Vaswani 2017, 2. Find efficiency papers,
               3. Categorize approaches, 4. Synthesize findings"
    
    2. USER PROFILE may learn:
       - Research interest: Transformers, attention mechanisms
       - Domain: Machine learning / NLP
    
    3. ENTITY MEMORY seeds:
       - Paper: "Attention Is All You Need (Vaswani et al., 2017)"
       - Concept: "Attention mechanisms"
       - Concept: "Transformer architecture"
    
    
    Agent responds:
    "I'll help you with this literature review. Let me outline our
     research plan:
     
     1. **Foundation**: Start with Vaswani et al. 2017
     2. **Efficiency variants**: Linear attention, sparse attention,
        local attention approaches
     3. **Key papers**: Linformer, Performer, BigBird, Longformer
     4. **Recent developments**: Flash Attention, Ring Attention
     
     Shall I start by summarizing the key efficiency bottlenecks
     that these papers address?"
    """)


def demo_entity_building():
    """Show how research entities accumulate."""
    print("\n" + "=" * 60)
    print("ENTITY BUILDING")
    print("=" * 60)

    print("""
    As research progresses, entities accumulate:
    
    PAPERS:
    ┌─────────────────────────────────────────────────────────────┐
    │ "Attention Is All You Need"                                 │
    │  • authors: Vaswani et al.                                  │
    │  • year: 2017                                               │
    │  • key_contribution: Original transformer architecture      │
    │  • cited_by: [Linformer, Performer, ...]                   │
    │  • relevance: Foundation paper                              │
    └─────────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────────┐
    │ "Linformer"                                                 │
    │  • authors: Wang et al.                                     │
    │  • year: 2020                                               │
    │  • key_contribution: Linear complexity attention            │
    │  • approach: Low-rank projection                            │
    │  • limitation: Fixed sequence length                        │
    └─────────────────────────────────────────────────────────────┘
    
    AUTHORS:
    ┌─────────────────────────────────────────────────────────────┐
    │ "Ashish Vaswani"                                            │
    │  • affiliation: Google Brain (2017)                         │
    │  • papers: [Attention Is All You Need, ...]                │
    │  • research_focus: Transformers, attention                  │
    └─────────────────────────────────────────────────────────────┘
    
    CONCEPTS:
    ┌─────────────────────────────────────────────────────────────┐
    │ "Self-Attention"                                            │
    │  • definition: Mechanism to weigh input elements            │
    │  • complexity: O(n²) in sequence length                     │
    │  • variants: [multi-head, linear, sparse, local]           │
    │  • key_papers: [Vaswani 2017, ...]                         │
    └─────────────────────────────────────────────────────────────┘
    
    
    Later queries can leverage this:
    
    Researcher: "What approaches reduce attention complexity?"
    
    Agent can traverse entities to find:
    - All papers with efficiency improvements
    - Their specific approaches
    - Trade-offs and limitations
    """)


def demo_knowledge_capture():
    """Show how research patterns are captured."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE CAPTURE")
    print("=" * 60)

    print("""
    Agent captures reusable research insights:
    
    METHODOLOGY PATTERN:
    {
      "title": "Efficient Attention Literature Review Structure",
      "approach": [
        "Start with foundational paper (Vaswani 2017)",
        "Identify complexity bottleneck (O(n²))",
        "Categorize solutions by approach type",
        "Compare empirical results on benchmarks",
        "Note theoretical vs practical trade-offs"
      ],
      "useful_benchmarks": ["Long Range Arena", "GLUE", "WikiText"],
      "key_comparison_dimensions": [
        "Time complexity",
        "Memory complexity", 
        "Quality retention",
        "Implementation difficulty"
      ]
    }
    
    SYNTHESIS PATTERN:
    {
      "title": "Attention Efficiency Trade-offs",
      "insight": "Most efficient attention variants sacrifice some 
                 quality for speed. Flash Attention is unique in
                 achieving speedup without quality loss through
                 hardware-aware implementation.",
      "categories": {
        "approximate": ["Linformer", "Performer"],
        "sparse": ["BigBird", "Longformer"],
        "io_optimized": ["Flash Attention"]
      }
    }
    
    
    Future research on similar topics benefits from these patterns.
    """)


def demo_returning_researcher():
    """Show continuity for returning researchers."""
    print("\n" + "=" * 60)
    print("RETURNING RESEARCHER")
    print("=" * 60)

    print("""
    Same researcher, new session:
    
    Researcher: "Now I want to look at vision transformers"
    
    Agent has context:
    
    FROM USER PROFILE:
    - Expert in transformer architectures
    - Previous work on attention efficiency
    - Prefers structured literature reviews
    
    FROM ENTITY MEMORY:
    - Existing knowledge of base transformer
    - Understanding of attention mechanisms
    - Familiarity with efficiency concepts
    
    
    Agent responds:
    "Great, let's explore Vision Transformers! Building on your
     attention mechanism expertise, I'll focus on:
     
     1. **ViT foundation**: Dosovitskiy et al. 2020
     2. **Efficiency in vision**: How the techniques you studied
        (sparse attention, linear attention) apply to images
     3. **Vision-specific innovations**: Patch embedding, 
        position encoding for 2D
     
     Since you've covered attention efficiency, shall I emphasize
     how those techniques translate to the vision domain?"
    
    
    Benefits:
    ✓ Builds on existing knowledge
    ✓ Appropriate depth level
    ✓ Connected to previous research
    ✓ No redundant explanations
    """)


# =============================================================================
# CONFIGURATION OPTIONS
# =============================================================================


def show_configuration_options():
    """Different research agent configurations."""
    print("\n" + "=" * 60)
    print("CONFIGURATION OPTIONS")
    print("=" * 60)

    print("""
    INDIVIDUAL RESEARCHER (Private entities):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"user:{researcher_id}",  # Private
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"user:{researcher_id}",  # Private
        ),
    
    
    RESEARCH LAB (Shared domain knowledge):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"lab:{lab_id}",  # Lab-shared
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"lab:{lab_id}",  # Lab-shared
        ),
    
    
    DOMAIN-SPECIFIC (Community knowledge):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"user:{researcher_id}:ml",  # Private entities
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="domain:machine_learning",  # Community-shared
        ),
    
    
    MULTI-DOMAIN RESEARCHER:
    
        # Create separate agents per domain
        ml_agent = create_research_agent(
            researcher_id=user_id,
            research_domain="machine_learning",
        )
        
        bio_agent = create_research_agent(
            researcher_id=user_id,
            research_domain="biology",
        )
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN: RESEARCH AGENT")
    print("=" * 60)

    demo_research_session()
    demo_entity_building()
    demo_knowledge_capture()
    demo_returning_researcher()
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Research Agent Learning Setup:
    
    USER PROFILE
    - Research interests and expertise
    - Preferred methodologies
    - Domain knowledge level
    
    SESSION CONTEXT
    - Current research question
    - Research plan and progress
    - Findings so far
    
    ENTITY MEMORY
    - Papers and their attributes
    - Authors and affiliations
    - Concepts and definitions
    - Relationships (citations, builds-on)
    
    LEARNED KNOWLEDGE
    - Literature review methodologies
    - Synthesis patterns
    - Domain-specific insights
    
    Benefits:
    ✓ Accumulated domain knowledge
    ✓ Connected research entities
    ✓ Reusable research patterns
    ✓ Personalized assistance
    """)
