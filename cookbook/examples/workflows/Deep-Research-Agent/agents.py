import os
from pathlib import Path
from dotenv import load_dotenv
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.wikipedia import WikipediaTools
from agno.tools.arxiv import ArxivTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.github import GithubTools

# Load environment variables
load_dotenv()

# Setup database in tmp folder
tmp_dir = Path("tmp")
tmp_dir.mkdir(exist_ok=True)

db_path = os.getenv("DATABASE_PATH", str(tmp_dir / "research_agent.db"))
db = SqliteDb(
    db_file=db_path,
    session_table="research_sessions",
    memory_table="research_memories",
)

search_orchestrator = Agent(
    name="Search Orchestrator",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        DuckDuckGoTools(),
        WikipediaTools(),
        ArxivTools(),
        HackerNewsTools(),
        GithubTools(),
    ],
    instructions="""Gather comprehensive technical sources based on the user query. 
    
    CRITICAL: Use ALL available tools for thorough research coverage:
    1. ALWAYS use DuckDuckGoTools for general web search and technical blogs.
    2. ALWAYS use GithubTools for GitHub repository searches - it provides structured repository data.
    3. ALWAYS use WikipediaTools for foundational research, definitions, and reference information.
    4. ALWAYS use ArxivTools to search for academic research papers and scientific publications.
    5. ALWAYS use HackerNewsTools for tech community discussions, real-world implementations, and industry trends.
    
    Research Strategy:
    - Perform searches using EACH tool to ensure comprehensive coverage from multiple source types.
    - Iterate on searches across all tools to follow leads and gather diverse perspectives.
    - Aim for at least 3-5 sources from each tool category when relevant to the query.
    - For GitHub searches, prioritize using GithubTools for structured repository data when available.
    - Collect multiple high-quality sources covering different aspects: theory, practice, community insights, and academic research.
    
    Output:
    - Organize sources by tool/source type (Web, GitHub Repos, Wikipedia, Academic Papers, Community Discussions).
    - Return a comprehensive list of relevant sources with URLs and brief descriptions.
    - Include sources from all tool categories to provide a well-rounded research base.""",
    db=db,
    enable_user_memories=True,
)

evidence_extractor = Agent(
    name="Evidence Extractor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""Process gathered sources from the Search Orchestrator and extract comprehensive evidence.
    
    Analysis Requirements:
    - Read and analyze each source thoroughly to extract key technical concepts, methodologies, and findings.
    - Identify and document trade-offs, limitations, and considerations mentioned in sources.
    - Extract any benchmarks, metrics, performance data, or quantitative evidence.
    - Note conflicting viewpoints or alternative approaches presented across sources.
    
    Source Evaluation:
    - Assess the credibility and authority of each source (author expertise, publication venue, recency).
    - Identify potential biases or limitations in the sources.
    - Prioritize information from authoritative sources (research papers, official docs, reputable blogs).
    
    Citation Format:
    - Format each extracted evidence piece with: [Key Finding] - Source: [Title/Description] - URL: [Source URL]
    - Maintain proper attribution for all quotes, data points, and specific claims.
    - Include publication dates when available to indicate recency.
    
    Organization:
    - Group extracted evidence by themes or topics (e.g., "Performance Metrics", "Architecture Patterns", "Security Considerations").
    - Create a structured summary for each source covering main points and key takeaways.
    - Prepare evidence in a format ready for synthesis into a cohesive report.""",
    db=db,
    enable_user_memories=True,
)

report_synthesizer = Agent(
    name="Report Synthesizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""Transform extracted evidence into a comprehensive, well-structured research report.
    
    Report Structure:
    - **Background/Context**: Provide necessary context about the topic, its significance, and current state of the field.
    - **Key Findings**: Synthesize the most important discoveries, insights, and facts from all sources.
    - **Alternatives/Options**: Present different approaches, solutions, or methodologies identified in the research.
    - **Trade-offs Analysis**: Compare alternatives, highlighting advantages, disadvantages, and when each approach is suitable.
    - **Recommendations**: Provide actionable recommendations based on the evidence, with clear reasoning.
    - **References**: List all sources with proper citations and URLs for further reading.
    
    Synthesis Approach:
    - Integrate information from multiple sources into a coherent narrative without repetition.
    - Resolve contradictions by presenting balanced perspectives and noting areas of disagreement.
    - Build logical flow between sections, connecting findings to conclusions.
    - Use evidence to support claims, avoiding unsupported assertions.
    
    Citation Standards:
    - Include in-text citations (Author/Source, Year) throughout the report for all claims and data.
    - Maintain all source URLs in the References section.
    - Format citations consistently and make them easy to verify.
    
    Formatting:
    - Use clear markdown structure with proper heading hierarchy (H1, H2, H3).
    - Include tables, lists, and code blocks where appropriate for clarity.
    - Ensure the report is professional, readable, and ready for developer review or documentation.
    - Add a summary/executive summary section at the beginning for quick reference.""",
    db=db,
    enable_user_memories=True,
)
