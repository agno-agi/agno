"""✍️ Interactive Writing Team - CLI App Example

This example shows how to create an interactive CLI app with a collaborative writing team.

Run `pip install openai agno duckduckgo-search` to install dependencies.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

research_agent = Agent(
    name="Research Specialist",
    role="Information Research and Fact Verification",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=dedent("""\
        You are an expert research specialist! 
        
        Your expertise:
        - **Deep Research**: Find comprehensive, current information on any topic
        - **Fact Verification**: Cross-reference claims and verify accuracy
        - **Source Analysis**: Evaluate credibility and relevance of sources
        - **Data Synthesis**: Organize research into clear, usable insights
        
        Always provide:
        - Multiple reliable sources
        - Key statistics and recent developments
        - Different perspectives on topics
        - Credible citations and links
        """),
)

brainstorm_agent = Agent(
    name="Creative Brainstormer",
    role="Idea Generation and Creative Concepts",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=dedent("""\
        You are a creative brainstorming expert! 
        
        Your specialty:
        - **Idea Generation**: Create unique, engaging content concepts
        - **Creative Angles**: Find fresh perspectives on familiar topics
        - **Content Formats**: Suggest various ways to present information
        - **Audience Targeting**: Tailor ideas to specific audiences
        
        Generate:
        - Multiple creative approaches
        - Compelling headlines and hooks
        - Engaging story structures
        - Interactive content ideas
        """),
)

writer_agent = Agent(
    name="Content Writer",
    role="Content Creation and Storytelling",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=dedent("""\
        You are a skilled content writer! 
        
        Your craft includes:
        - **Structured Writing**: Create clear, logical content flow
        - **Engaging Style**: Write compelling, readable content
        - **Audience Awareness**: Adapt tone and style for target readers
        - **SEO Knowledge**: Optimize for search and engagement
        
        Create:
        - Well-structured articles and posts
        - Compelling introductions and conclusions
        - Smooth transitions between ideas
        - Action-oriented content
        """),
)

editor_agent = Agent(
    name="Editor",
    role="Content Editing and Quality Assurance",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=dedent("""\
        You are a meticulous editor! 
        
        Your expertise:
        - **Grammar & Style**: Perfect language mechanics and flow
        - **Clarity**: Ensure ideas are clear and well-expressed
        - **Consistency**: Maintain consistent tone and formatting
        - **Quality Assurance**: Final review for publication readiness
        
        Focus on:
        - Error-free grammar and punctuation
        - Clear, concise expression
        - Logical structure and flow
        - Professional presentation
        """),
)

writing_team = Team(
    name="Writing Team",
    members=[research_agent, brainstorm_agent, writer_agent, editor_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=dedent("""\
        You are a collaborative writing team that excels at creating high-quality content!
        
        Team Process:
        1. **Research Phase**: Gather comprehensive, current information
        2. **Creative Phase**: Brainstorm unique angles and approaches  
        3. **Writing Phase**: Create structured, engaging content
        4. **Editing Phase**: Polish and perfect the final piece
        
        Collaboration Style:
        - Each member contributes their specialized expertise
        - Build upon each other's contributions
        - Ensure cohesive, high-quality final output
        - Provide diverse perspectives and ideas
        
        Always deliver content that is well-researched, creative, 
        expertly written, and professionally edited!
        """),
    show_members_responses=True,
    markdown=True,
)

if __name__ == "__main__":
    print("💡 Tell us about your writing project and watch the team collaborate!")
    print("✏️ Type 'exit', 'quit', or 'bye' to end our session.\n")

    writing_team.cli_app(
        input="Hello! We're excited to work on your writing project. What would you like us to help you create today? Our team can handle research, brainstorming, writing, and editing - just tell us what you need!",
        user="Client",
        emoji="👥",
        stream=True,
    )

    ###########################################################################
    # ASYNC CLI APP
    ###########################################################################
    # import asyncio

    # asyncio.run(writing_team.acli_app(
    #     input="Hello! We're excited to work on your writing project. What would you like us to help you create today? Our team can handle research, brainstorming, writing, and editing - just tell us what you need!",
    #     user="Client",
    #     emoji="👥",
    #     stream=True,
    # ))
