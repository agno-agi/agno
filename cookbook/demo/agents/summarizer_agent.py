"""
Summarizer Agent - Condenses long-form content into structured summaries.

This agent specializes in:
- Summarizing documents, articles, and transcripts
- Extracting key points and action items
- Producing concise executive summaries
- Supporting multiple summary formats (bullet, paragraph, structured)

Example queries:
- "Summarize this article: [paste text or URL]"
- "Give me key takeaways from this meeting transcript"
- "Extract the main arguments and conclusion from this document"
- "Create a one-paragraph executive summary of the following"
"""

import sys
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Summarizer Agent - an expert at distilling long-form content
    into clear, structured summaries that preserve key information and action items.
    """)

instructions = dedent("""\
    You are a professional summarizer. Your job is to take long-form content and
    produce accurate, well-structured summaries.

    SUMMARIZATION PROCESS:

    1. **Analyze the Input**
       - Identify the type of content (article, transcript, report, etc.)
       - Determine the main purpose and audience
       - Note any explicit or implied structure

    2. **Extract Key Information**
       - Main thesis or central claim
       - Supporting arguments or evidence
       - Key facts, figures, and dates
       - Conclusions and recommendations
       - Action items or next steps (if present)

    3. **Choose Output Format**
       - **Executive summary**: One paragraph, high-level overview
       - **Bullet summary**: Key points as concise bullets
       - **Structured summary**: Sections matching original (e.g., Background, Findings, Conclusion)
       - **TL;DR**: Ultra-brief (1-3 sentences) when appropriate

    4. **Quality Standards**
       - Preserve accurate meaning; do not distort or add interpretation
       - Omit filler and redundancy
       - Keep technical terms when they matter; explain only if requested
       - Note uncertainty or gaps if the source is ambiguous

    5. **When Content Is Provided via URL or "Summarize this"**
       - Use search/extract tools to obtain the content when needed
       - If the user pastes text, work directly from it
       - If asked to summarize a URL, fetch and then summarize

    OUTPUT FORMAT (adapt to request):

    ## Summary: [Topic or Title]

    ### Key Points
    - [Point 1]
    - [Point 2]
    - [Point 3]

    ### Conclusion / Main Takeaway
    [One or two sentences]

    ### Action Items (if any)
    - [Item 1]
    - [Item 2]

    Keep tone neutral and factual. No emojis.
    """)

# ============================================================================
# Create the Agent
# ============================================================================
summarizer_agent = Agent(
    name="Summarizer Agent",
    role="Condense long-form content into structured, actionable summaries",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[
        ReasoningTools(add_instructions=True),
        ParallelTools(enable_search=True, enable_extract=True),
    ],
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Summarizer Agent")
    print("   Condenses long-form content into structured summaries")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        summarizer_agent.print_response(message, stream=True)
    else:
        # Run demo tests
        sample_text = (
            "Agno is an open-source framework for building AI agents. "
            "It supports single agents, teams, and workflows. Key features include "
            "tools, knowledge/RAG, memory, and structured output. Use PostgreSQL "
            "in production and SQLite for development. Start with one agent and "
            "scale up only when needed."
        )
        print("\n--- Demo 1: Inline Text Summary ---")
        summarizer_agent.print_response(
            f"Summarize this in 3 bullet points:\n\n{sample_text}",
            stream=True,
        )

        print("\n--- Demo 2: Executive Summary Style ---")
        summarizer_agent.print_response(
            "Give a one-paragraph executive summary of what Agno is and who it's for.",
            stream=True,
        )
