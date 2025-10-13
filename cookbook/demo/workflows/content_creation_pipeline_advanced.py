"""
Enhanced Content Creation Pipeline - Advanced Workflow with Router, Parallel, Conditional, and Loop patterns

This workflow demonstrates:
- Parallel research from multiple sources
- Router for content type selection (blog, social media, technical doc)
- Conditional SEO optimization
- Loop for quality validation
- Early stopping for safety checks
"""

from textwrap import dedent
from typing import List

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.newspaper4k import Newspaper4kTools
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")

# ============================================================================
# Data Models
# ============================================================================


class ContentBrief(BaseModel):
    """Structured content brief"""

    topic: str
    target_audience: str
    tone: str
    word_count: int
    key_points: list[str]
    seo_keywords: list[str]


# ============================================================================
# Research Agents
# ============================================================================

hackernews_researcher = Agent(
    name="HackerNews Researcher",
    role="Researches tech trends from HackerNews",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert at finding trending tech topics and discussions on HackerNews",
    instructions=[
        "Search for the most discussed and trending tech topics",
        "Find relevant HackerNews discussions and comments",
        "Identify key insights from the community",
        "Note any controversies or debates",
    ],
    tools=[HackerNewsTools()],
    db=db,
    markdown=True,
)

web_researcher = Agent(
    name="Web Researcher",
    role="Researches topics from web sources",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert at finding authoritative web content and recent news",
    instructions=[
        "Search for the most recent and authoritative information",
        "Find 5-10 high-quality sources",
        "Verify facts across multiple sources",
        "Compile key statistics and quotes",
    ],
    tools=[DuckDuckGoTools()],
    db=db,
    markdown=True,
)

news_researcher = Agent(
    name="News Researcher",
    role="Researches news articles",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert at extracting insights from news articles",
    instructions=[
        "Find and analyze relevant news articles",
        "Extract key facts and quotes",
        "Identify emerging trends",
        "Note publication dates and sources",
    ],
    tools=[Newspaper4kTools()],
    db=db,
    markdown=True,
)

# ============================================================================
# Content Creation Agents
# ============================================================================

blog_writer = Agent(
    name="Blog Writer",
    role="Writes engaging blog posts",
    model=Claude(id="claude-sonnet-4-20250514"),
    description="Professional blog writer specializing in engaging, conversational content",
    instructions=[
        "Write in a conversational, engaging tone",
        "Use storytelling techniques",
        "Include personal examples and anecdotes",
        "Create compelling headlines and subheadings",
        "Use bullet points and formatting for readability",
        "Aim for 800-1200 words",
    ],
    db=db,
    markdown=True,
)

social_media_writer = Agent(
    name="Social Media Writer",
    role="Creates social media content",
    model=OpenAIChat(id="gpt-4o"),
    description="Expert at creating viral, engaging social media content",
    instructions=[
        "Write punchy, attention-grabbing content",
        "Use emojis and hashtags strategically",
        "Create multiple variations (Twitter, LinkedIn, Instagram)",
        "Include call-to-actions",
        "Keep it concise and impactful",
    ],
    db=db,
    markdown=True,
)

technical_writer = Agent(
    name="Technical Writer",
    role="Writes technical documentation",
    model=Claude(id="claude-sonnet-4-20250514"),
    description="Expert technical writer specializing in clear, precise documentation",
    instructions=[
        "Write in a clear, precise, technical style",
        "Use proper technical terminology",
        "Include code examples where relevant",
        "Create detailed step-by-step instructions",
        "Structure with clear sections and hierarchy",
        "Aim for completeness and accuracy",
    ],
    db=db,
    markdown=True,
)

seo_optimizer = Agent(
    name="SEO Optimizer",
    role="Optimizes content for SEO",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="SEO expert who optimizes content for search engines",
    instructions=[
        "Add relevant keywords naturally",
        "Optimize headlines and meta descriptions",
        "Improve internal linking suggestions",
        "Add schema markup recommendations",
        "Enhance readability for both users and search engines",
    ],
    db=db,
    markdown=True,
)

content_editor = Agent(
    name="Content Editor",
    role="Edits and refines content",
    model=OpenAIChat(id="gpt-4o"),
    description="Meticulous editor focused on quality and clarity",
    instructions=[
        "Check for grammar, spelling, and punctuation",
        "Improve sentence structure and flow",
        "Ensure logical organization",
        "Verify factual accuracy",
        "Enhance clarity and readability",
        "Provide quality score (1-10)",
    ],
    db=db,
    markdown=True,
)

# ============================================================================
# Workflow Steps
# ============================================================================

# Research Steps (Parallel)
research_hackernews_step = Step(
    name="ResearchHackerNews",
    description="Research tech trends from HackerNews",
    agent=hackernews_researcher,
)

research_web_step = Step(
    name="ResearchWeb",
    description="Research from web sources",
    agent=web_researcher,
)

research_news_step = Step(
    name="ResearchNews",
    description="Research news articles",
    agent=news_researcher,
)

# Content Creation Steps (Router choices)
blog_writing_step = Step(
    name="WriteBlogPost",
    description="Write an engaging blog post",
    agent=blog_writer,
)

social_media_step = Step(
    name="CreateSocialMedia",
    description="Create social media content",
    agent=social_media_writer,
)

technical_doc_step = Step(
    name="WriteTechnicalDoc",
    description="Write technical documentation",
    agent=technical_writer,
)

# SEO Optimization Step (Conditional)
seo_optimization_step = Step(
    name="OptimizeForSEO",
    description="Optimize content for SEO",
    agent=seo_optimizer,
)

# Editing Step (Loop)
editing_step = Step(
    name="EditContent",
    description="Edit and refine content",
    agent=content_editor,
)


# ============================================================================
# Custom Functions for Workflow Logic
# ============================================================================


def content_type_router(step_input: StepInput) -> List[Step]:
    """Route to appropriate content creation agent based on input"""
    topic = (step_input.input or "").lower()

    # Determine content type from topic
    if any(keyword in topic for keyword in ["social media", "tweet", "post", "instagram", "linkedin"]):
        print(f"📱 Routing to Social Media Writer for: {topic[:50]}...")
        return [social_media_step]
    elif any(keyword in topic for keyword in ["technical", "documentation", "api", "guide", "tutorial"]):
        print(f"📚 Routing to Technical Writer for: {topic[:50]}...")
        return [technical_doc_step]
    else:
        print(f"📝 Routing to Blog Writer for: {topic[:50]}...")
        return [blog_writing_step]


def should_optimize_seo(step_input: StepInput) -> bool:
    """Determine if SEO optimization is needed"""
    topic = (step_input.input or "").lower()

    # Only optimize for blog posts and technical docs, not social media
    needs_seo = any(keyword in topic for keyword in ["blog", "article", "guide", "tutorial", "documentation"])

    print(f"🔍 SEO Optimization needed: {needs_seo}")
    return needs_seo


def quality_check(outputs: List[StepOutput]) -> bool:
    """Check content quality and decide if editing loop should continue"""
    if not outputs:
        return False

    last_content = str(outputs[-1].content or "")

    # Simple quality checks
    has_good_length = len(last_content) > 300
    has_structure = any(marker in last_content for marker in ["##", "###", "- ", "1."])

    # Check for quality score in content (if editor provided it)
    quality_threshold_met = "quality score" in last_content.lower() and any(
        score in last_content.lower() for score in ["8/10", "9/10", "10/10", "8.", "9.", "10."]
    )

    should_continue = not (has_good_length and has_structure and quality_threshold_met)

    if should_continue:
        print(f"🔄 Quality check: Content needs improvement. Continuing loop...")
    else:
        print(f"✅ Quality check: Content meets quality standards. Ending loop.")

    # Return True to STOP the loop
    return not should_continue


def safety_check(step_input: StepInput) -> StepOutput:
    """Safety gate that can stop workflow if inappropriate content detected"""
    content = step_input.previous_step_content or ""

    # Simple safety check
    unsafe_keywords = ["explicit", "inappropriate", "offensive", "harmful"]
    if any(keyword in content.lower() for keyword in unsafe_keywords):
        return StepOutput(
            content="⚠️ SAFETY ALERT: Inappropriate content detected. Workflow stopped.",
            stop=True,  # Stop the entire workflow
        )

    return StepOutput(
        content=content,
        stop=False,  # Continue workflow
    )


# ============================================================================
# Main Workflow
# ============================================================================

content_creation_workflow_advanced = Workflow(
    name="Enhanced Content Creation Pipeline",
    description=dedent("""\
        Advanced content creation workflow with intelligent routing and quality control.

        Features:
        - Parallel research from HackerNews, Web, and News sources
        - Smart routing to Blog, Social Media, or Technical writers based on content type
        - Conditional SEO optimization for web content
        - Quality-driven editing loop
        - Safety gate for content validation
    """),
    steps=[
        # Phase 1: Parallel Research
        Parallel(
            research_hackernews_step,
            research_web_step,
            research_news_step,
            name="ResearchPhase",
            description="Gather information from multiple sources in parallel",
        ),
        # Phase 2: Safety Check
        Step(
            name="SafetyGate",
            executor=safety_check,
            description="Validate research content for safety",
        ),
        # Phase 3: Content Type Routing
        Router(
            name="ContentTypeRouter",
            selector=content_type_router,
            choices=[blog_writing_step, social_media_step, technical_doc_step],
            description="Route to appropriate content writer based on content type",
        ),
        # Phase 4: Conditional SEO Optimization
        Condition(
            name="SEOOptimization",
            evaluator=should_optimize_seo,
            steps=[seo_optimization_step],
            description="Optimize for SEO if needed",
        ),
        # Phase 5: Quality-Driven Editing Loop
        Loop(
            name="QualityEditingLoop",
            steps=[editing_step],
            end_condition=quality_check,
            max_iterations=3,
            description="Edit content until quality standards are met",
        ),
    ],
    db=db,
    store_events=True,  # Store all workflow events for debugging
    markdown=True,
)


# ============================================================================
# Usage Examples
# ============================================================================

if __name__ == "__main__":
    # Example 1: Blog post (will use blog writer + SEO)
    print("\n" + "=" * 80)
    print("Example 1: Blog Post Creation")
    print("=" * 80)
    content_creation_workflow_advanced.print_response(
        "Write a blog post about the latest AI developments in 2024", stream=True, stream_intermediate_steps=True
    )

    # Example 2: Social media content (will use social media writer, skip SEO)
    print("\n" + "=" * 80)
    print("Example 2: Social Media Content")
    print("=" * 80)
    content_creation_workflow_advanced.print_response(
        "Create social media content about quantum computing breakthroughs",
        stream=True,
        stream_intermediate_steps=True,
    )

    # Example 3: Technical documentation (will use technical writer + SEO)
    print("\n" + "=" * 80)
    print("Example 3: Technical Documentation")
    print("=" * 80)
    content_creation_workflow_advanced.print_response(
        "Write technical documentation for REST API best practices",
        stream=True,
        stream_intermediate_steps=True,
    )
