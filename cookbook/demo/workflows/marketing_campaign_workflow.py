"""🎯 Content Marketing Campaign Generator - Multi-Channel Content Automation

This workflow demonstrates advanced Agno workflow patterns for automated marketing campaigns:
- Parallel market research from multiple sources
- Iterative content generation with SEO and readability quality gates
- Parallel multi-format content production (blog, social, email)
- Session state management for campaign context
- Structured I/O with Pydantic models

Business Value: 10x faster campaign creation, consistent brand voice, SEO-optimized content
"""

from textwrap import dedent
from typing import List, Literal, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.wikipedia import WikipediaTools
from agno.workflow import Loop, Parallel, Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field

# ============================================================================
# Database Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="marketing_workflow_db")

# ============================================================================
# Pydantic Models for Structured I/O
# ============================================================================


class CampaignRequest(BaseModel):
    """Input schema for marketing campaign requests"""

    topic: str = Field(description="Main campaign topic or theme")
    target_audience: str = Field(description="Primary target audience description")
    tone: Literal["professional", "casual", "technical", "friendly"] = Field(
        description="Desired content tone"
    )
    goals: List[str] = Field(description="Campaign goals and objectives")
    distribution_channels: List[str] = Field(
        description="Channels for content distribution"
    )
    keywords: Optional[List[str]] = Field(
        default=None, description="Target SEO keywords"
    )


class ContentAsset(BaseModel):
    """Individual content asset with quality metrics"""

    asset_type: Literal["blog", "twitter", "linkedin", "email", "meta_description"]
    content: str = Field(description="The actual content text")
    word_count: int = Field(description="Number of words in content")
    seo_score: Optional[float] = Field(
        default=None, ge=0.0, le=100.0, description="SEO optimization score (0-100)"
    )
    readability_score: Optional[float] = Field(
        default=None, ge=0.0, le=100.0, description="Readability score (0-100)"
    )
    estimated_reach: Optional[int] = Field(
        default=None, description="Estimated audience reach"
    )


class CampaignOutput(BaseModel):
    """Complete campaign output with all assets"""

    campaign_theme: str = Field(description="Overall campaign theme and messaging")
    blog_post: ContentAsset = Field(description="Main blog post content")
    social_posts: List[ContentAsset] = Field(
        description="Social media posts for various platforms"
    )
    email_content: ContentAsset = Field(description="Email newsletter content")
    meta_description: str = Field(description="SEO meta description")
    target_keywords: List[str] = Field(description="Primary SEO keywords used")
    distribution_plan: dict = Field(description="Recommended distribution timeline")


# ============================================================================
# Market Research Agents (Parallel Execution)
# ============================================================================

trend_analysis_agent = Agent(
    name="Trend Analyst",
    model=Claude(id="claude-sonnet-4-0"),
    role="Analyze current trends and hot topics",
    tools=[HackerNewsTools(), DuckDuckGoTools()],
    instructions=dedent("""\
        You are a trend analyst specializing in identifying emerging topics and viral content.

        Your responsibilities:
        1. Search HackerNews for trending technical discussions
        2. Analyze current hot topics in the industry
        3. Identify emerging themes and conversations
        4. Assess topic popularity and engagement potential

        Focus on:
        - Recent discussions and comments
        - Upvote patterns and engagement levels
        - Emerging technologies and methods
        - Community sentiment and reactions

        Provide insights on:
        - What's currently trending
        - Why certain topics are gaining traction
        - How to position content for maximum engagement
        \
    """),
)

competitor_analysis_agent = Agent(
    name="Competitor Analyst",
    model=Claude(id="claude-sonnet-4-0"),
    role="Analyze competitor content and positioning",
    tools=[DuckDuckGoTools()],
    instructions=dedent("""\
        You are a competitive intelligence analyst tracking competitor content strategies.

        Your responsibilities:
        1. Search for competitor content on similar topics
        2. Analyze their messaging and positioning
        3. Identify content gaps and opportunities
        4. Assess engagement and performance

        Look for:
        - Popular competitor blog posts and articles
        - Social media content and engagement
        - Content formats and styles that work
        - Unique angles and perspectives

        Provide insights on:
        - What competitors are doing well
        - Content gaps we can fill
        - Differentiation opportunities
        - Best practices to adopt or improve
        \
    """),
)

audience_research_agent = Agent(
    name="Audience Researcher",
    model=Claude(id="claude-sonnet-4-0"),
    role="Research target audience needs and interests",
    tools=[WikipediaTools(), DuckDuckGoTools()],
    instructions=dedent("""\
        You are an audience researcher understanding what target audiences care about.

        Your responsibilities:
        1. Research the target audience demographics and psychographics
        2. Understand their pain points and challenges
        3. Identify their goals and aspirations
        4. Discover their preferred content formats

        Focus on:
        - Common questions and problems
        - Information needs and knowledge gaps
        - Learning preferences and styles
        - Vocabulary and language they use

        Provide insights on:
        - What resonates with this audience
        - How to frame the topic for them
        - Language and tone preferences
        - Content formats they prefer
        \
    """),
)

# ============================================================================
# Content Generation Agents
# ============================================================================

blog_writer_agent = Agent(
    name="Blog Content Writer",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create engaging, SEO-optimized blog content",
    instructions=dedent("""\
        You are an expert blog writer creating high-quality, engaging content.

        Your responsibilities:
        1. Write comprehensive, well-structured blog posts
        2. Optimize content for target SEO keywords naturally
        3. Create compelling headlines and subheadings
        4. Include actionable insights and examples
        5. Maintain consistent tone and brand voice

        Content guidelines:
        - Length: 800-1200 words for optimal SEO
        - Structure: Clear introduction, body, conclusion
        - Readability: Use short paragraphs, bullet points, examples
        - SEO: Include keywords naturally without keyword stuffing
        - Value: Provide practical, actionable information

        Quality standards:
        - Original insights and perspectives
        - Well-researched and accurate information
        - Engaging storytelling and examples
        - Clear call-to-action
        - Professional yet accessible tone
        \
    """),
)

social_media_agent = Agent(
    name="Social Media Specialist",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create platform-specific social media content",
    instructions=dedent("""\
        You are a social media specialist creating engaging posts for different platforms.

        Platform specifications:
        - Twitter: 280 characters, punchy and engaging, 2-3 hashtags
        - LinkedIn: Professional tone, 150-300 words, insights-focused
        - Instagram: Visual focus, storytelling, 5-10 relevant hashtags

        Content guidelines:
        - Hook: Grab attention in first line
        - Value: Provide clear takeaway or insight
        - Engagement: Encourage likes, comments, shares
        - Hashtags: Relevant and targeted to reach
        - Call-to-action: Clear next step for audience

        Create content that:
        - Stops the scroll with compelling hooks
        - Provides immediate value
        - Encourages engagement and conversation
        - Drives traffic to main content
        - Maintains brand voice across platforms
        \
    """),
)

email_writer_agent = Agent(
    name="Email Marketing Writer",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create compelling email newsletter content",
    instructions=dedent("""\
        You are an email marketing specialist creating high-converting newsletters.

        Email structure:
        1. Subject Line: Compelling, benefit-driven, 40-50 characters
        2. Preview Text: Supports subject, adds context
        3. Header: Personal greeting, sets context
        4. Body: Value-driven content, scannable format
        5. Call-to-Action: Clear, prominent, action-oriented
        6. Footer: Additional resources, social links

        Writing guidelines:
        - Personal: Write as one person to another
        - Conversational: Friendly and accessible tone
        - Scannable: Short paragraphs, bullet points, subheadings
        - Value-first: Lead with benefits and takeaways
        - Action-oriented: Clear next steps

        Optimize for:
        - Open rates: Compelling subject lines
        - Click-through: Strategic CTA placement
        - Readability: Mobile-friendly formatting
        - Engagement: Personalization and relevance
        \
    """),
)

# ============================================================================
# Quality Scoring Functions (Custom Functions)
# ============================================================================


def calculate_seo_score(content: str, keywords: List[str]) -> float:
    """
    Calculate SEO optimization score based on keyword usage and content quality.

    SEO factors:
    - Keyword presence in content
    - Keyword density (2-5% optimal)
    - Content length (800+ words optimal)
    - Structure (headings, lists, paragraphs)

    Args:
        content: The content text to analyze
        keywords: Target SEO keywords

    Returns:
        SEO score from 0-100
    """
    score = 0.0
    content_lower = content.lower()
    word_count = len(content.split())

    # Factor 1: Keyword presence (40 points)
    if keywords:
        keywords_found = sum(
            1 for keyword in keywords if keyword.lower() in content_lower
        )
        keyword_score = (keywords_found / len(keywords)) * 40
        score += keyword_score

    # Factor 2: Content length (30 points)
    if word_count >= 800:
        length_score = min(30, (word_count / 1200) * 30)
    else:
        length_score = (word_count / 800) * 30
    score += length_score

    # Factor 3: Structure (30 points)
    has_headings = any(marker in content for marker in ["##", "**", "__"])
    has_lists = any(marker in content for marker in ["- ", "* ", "1. "])
    has_paragraphs = "\n\n" in content

    structure_score = (
        (10 if has_headings else 0)
        + (10 if has_lists else 0)
        + (10 if has_paragraphs else 0)
    )
    score += structure_score

    return min(100.0, score)


def calculate_readability_score(content: str) -> float:
    """
    Calculate readability score based on sentence length and word complexity.

    Readability factors:
    - Average sentence length (15-20 words optimal)
    - Paragraph length (3-5 sentences optimal)
    - Use of transition words
    - Formatting (lists, headings, whitespace)

    Args:
        content: The content text to analyze

    Returns:
        Readability score from 0-100
    """
    score = 0.0
    sentences = [s.strip() for s in content.split(".") if s.strip()]
    words = content.split()
    word_count = len(words)

    if not sentences or not words:
        return 0.0

    # Factor 1: Sentence length (40 points)
    avg_sentence_length = word_count / len(sentences)
    if 15 <= avg_sentence_length <= 20:
        sentence_score = 40
    elif 10 <= avg_sentence_length <= 25:
        sentence_score = 30
    else:
        sentence_score = 20
    score += sentence_score

    # Factor 2: Paragraph structure (30 points)
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if len(paragraphs) >= 3:
        paragraph_score = 30
    else:
        paragraph_score = len(paragraphs) * 10
    score += paragraph_score

    # Factor 3: Formatting (30 points)
    has_lists = "- " in content or "* " in content
    has_headings = "##" in content or "**" in content
    has_whitespace = "\n\n" in content

    formatting_score = (
        (10 if has_lists else 0)
        + (10 if has_headings else 0)
        + (10 if has_whitespace else 0)
    )
    score += formatting_score

    return min(100.0, score)


def evaluate_content_quality(step_input: StepInput) -> StepOutput:
    """
    Evaluate blog content quality and add SEO/readability scores.

    Quality criteria:
    - SEO score > 80
    - Readability score > 70
    - Word count 800-1200

    Args:
        step_input: Contains blog content from previous step

    Returns:
        StepOutput with evaluated content and scores
    """
    # Get content from previous step
    blog_content = step_input.previous_step_content

    if not blog_content or not isinstance(blog_content, str):
        return StepOutput(content="⚠️  No content to evaluate", stop=False)

    # Get keywords from session state
    session_state = step_input.session_state or {}
    keywords = session_state.get("target_keywords", [])

    # Calculate scores
    seo_score = calculate_seo_score(blog_content, keywords)
    readability_score = calculate_readability_score(blog_content)
    word_count = len(blog_content.split())

    print(f"\n   📊 Content Quality Metrics:")
    print(f"      SEO Score: {seo_score:.1f}/100")
    print(f"      Readability Score: {readability_score:.1f}/100")
    print(f"      Word Count: {word_count}")

    # Store scores in session state for loop evaluation
    session_state["latest_seo_score"] = seo_score
    session_state["latest_readability_score"] = readability_score

    # Create content asset
    blog_asset = ContentAsset(
        asset_type="blog",
        content=blog_content,
        word_count=word_count,
        seo_score=seo_score,
        readability_score=readability_score,
    )

    return StepOutput(content=blog_asset.model_dump_json(), stop=False)


# ============================================================================
# Loop End Condition: Quality Gate
# ============================================================================


def check_content_quality(outputs: List[StepOutput]) -> bool:
    """
    Check if content meets quality standards to exit refinement loop.

    Quality gates:
    - SEO score > 80
    - Readability score > 70

    Args:
        outputs: List of step outputs from content generation

    Returns:
        True to exit loop (quality met), False to continue refining
    """
    if not outputs:
        print("   ❌ No content to evaluate")
        return False

    # Get the latest evaluation output
    latest_output = outputs[-1]

    # Try to parse as ContentAsset
    try:
        if isinstance(latest_output.content, str):
            import json

            content_data = json.loads(latest_output.content)
            seo_score = content_data.get("seo_score", 0)
            readability_score = content_data.get("readability_score", 0)

            print(f"\n   🎯 Quality Gate Check:")
            print(f"      SEO Score: {seo_score:.1f} (target: >80)")
            print(f"      Readability Score: {readability_score:.1f} (target: >70)")

            quality_met = seo_score > 80 and readability_score > 70

            if quality_met:
                print("   ✅ Quality gate passed - content ready for distribution!")
            else:
                print("   🔄 Quality gate not met - refining content...")

            return quality_met
    except Exception as e:
        print(f"   ⚠️  Error parsing content quality: {e}")

    # Fallback: allow after 2 iterations
    return len(outputs) >= 2


# ============================================================================
# Workflow Steps Definition
# ============================================================================

# Step 1: Parallel market research
parallel_research = Parallel(
    Step(
        name="analyze_trends",
        agent=trend_analysis_agent,
        description="Analyze current trends and hot topics",
    ),
    Step(
        name="analyze_competitors",
        agent=competitor_analysis_agent,
        description="Research competitor content and positioning",
    ),
    Step(
        name="research_audience",
        agent=audience_research_agent,
        description="Understand target audience needs and preferences",
    ),
    name="Market Research",
)

# Step 2: Blog content generation with quality loop
blog_generation_loop = Loop(
    steps=[
        Step(
            name="write_blog",
            agent=blog_writer_agent,
            description="Create SEO-optimized blog content",
        ),
        Step(
            name="evaluate_quality",
            executor=evaluate_content_quality,
            description="Evaluate content quality with SEO and readability scores",
        ),
    ],
    name="Content Generation & Refinement",
    end_condition=check_content_quality,
    max_iterations=3,
)

# Step 3: Parallel multi-format content production
parallel_content_production = Parallel(
    Step(
        name="create_twitter_post",
        agent=social_media_agent,
        description="Create engaging Twitter post (280 chars)",
    ),
    Step(
        name="create_linkedin_post",
        agent=social_media_agent,
        description="Create professional LinkedIn post (150-300 words)",
    ),
    Step(
        name="create_email",
        agent=email_writer_agent,
        description="Create compelling email newsletter",
    ),
    name="Multi-Format Production",
)

# ============================================================================
# Main Workflow Definition
# ============================================================================

marketing_campaign_workflow = Workflow(
    name="Content Marketing Campaign Generator",
    description="Automated multi-channel marketing campaign creation with quality optimization",
    db=db,
    steps=[
        # Phase 1: Market Research (Parallel)
        parallel_research,
        # Phase 2: Blog Content Generation (Iterative with Quality Gates)
        blog_generation_loop,
        # Phase 3: Multi-Format Content Production (Parallel)
        parallel_content_production,
    ],
    input_schema=CampaignRequest,
    session_state={},  # Initialize empty session state for campaign context
)


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    """
    Example usage demonstrating marketing campaign generation.
    """
    print("=" * 80)
    print("🎯 Marketing Campaign Workflow - Demo Example")
    print("=" * 80)

    # Example: AI-focused campaign
    campaign_request = CampaignRequest(
        topic="How AI agents are transforming customer support automation",
        target_audience="CTOs and engineering leaders at B2B SaaS companies",
        tone="professional",
        goals=[
            "Educate on AI agent capabilities",
            "Generate leads for AI platform",
            "Establish thought leadership",
        ],
        distribution_channels=["blog", "linkedin", "twitter", "email"],
        keywords=[
            "AI agents",
            "customer support automation",
            "LLM applications",
            "agentic workflows",
        ],
    )

    print("\n\n📝 Generating Marketing Campaign...")
    print("-" * 80)
    marketing_campaign_workflow.print_response(input=campaign_request, stream=True)
