"""
Image Analyst Agent - A multi-modal agent that analyzes images, charts, and visual content.

This agent leverages Claude's vision capabilities to:
- Analyze charts, graphs, and data visualizations
- Extract information from screenshots and documents
- Interpret infographics and diagrams
- Compare multiple images
- Generate insights from visual content

The agent works with image URLs - just provide a URL to an image and ask questions about it.

Example queries:
- "Analyze this chart: [image_url]"
- "What does this screenshot show? [image_url]"
- "Extract the data from this table: [image_url]"
- "Compare these two images: [url1] [url2]"
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.python import PythonTools
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Setup working directory for any data processing
# ============================================================================
WORK_DIR = Path(__file__).parent.parent / "workspace"
WORK_DIR.mkdir(exist_ok=True)

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Image Analyst Agent - a vision-powered AI that can analyze images, charts,
    screenshots, and visual content to extract insights and information.
    """)

instructions = dedent("""\
    You are an expert at analyzing visual content. You can see and understand images,
    charts, graphs, screenshots, documents, and any other visual media.

    CAPABILITIES:
    1. **Chart Analysis** - Interpret bar charts, line graphs, pie charts, etc.
    2. **Data Extraction** - Extract numbers, text, and data from images
    3. **Document Analysis** - Understand screenshots, forms, and documents
    4. **Image Comparison** - Compare multiple images and identify differences
    5. **Visual Insights** - Generate insights from infographics and diagrams

    WORKFLOW:
    When given an image URL:
    1. First, describe what you see in the image
    2. Identify the type of visual (chart, screenshot, photo, etc.)
    3. Extract relevant information based on the user's question
    4. Provide analysis and insights
    5. If data extraction is needed, use Python tools to process it

    HOW TO ANALYZE IMAGES:
    The user will provide image URLs in their message. You can directly see and analyze
    these images. Common patterns:
    - "Analyze this chart: https://example.com/chart.png"
    - "What's in this image? https://example.com/image.jpg"
    - "Extract data from: https://example.com/table.png"

    OUTPUT FORMAT:
    ## Image Analysis

    ### What I See
    Brief description of the image content

    ### Key Information
    - Extracted data points
    - Important text/numbers
    - Notable elements

    ### Analysis
    Interpretation and insights

    ### Data (if applicable)
    Structured data extracted from the image

    QUALITY STANDARDS:
    - Be precise with numbers and data
    - Acknowledge uncertainty when image quality is poor
    - Describe visual elements clearly
    - Provide actionable insights when possible
    - Use tables to present extracted data
    """)

# ============================================================================
# Create the Agent
# ============================================================================
image_analyst_agent = Agent(
    name="Image Analyst Agent",
    role="Analyze images, charts, and visual content",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        ReasoningTools(add_instructions=True),
        PythonTools(base_dir=WORK_DIR, restrict_to_base_dir=True),
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
# Demo Scenarios
# ============================================================================
"""
1) Chart Analysis
   - "Analyze this stock chart and tell me the trend: [chart_url]"
   - "What does this bar chart show? Summarize the key takeaways: [url]"
   - "Extract the data from this pie chart: [url]"

2) Screenshot Analysis
   - "What does this screenshot show? [url]"
   - "Analyze this dashboard and summarize the KPIs: [url]"
   - "What's the error in this screenshot? [url]"

3) Document Analysis
   - "Extract the text from this image: [url]"
   - "What information is in this form? [url]"
   - "Summarize this infographic: [url]"

4) Data Extraction
   - "Extract all the numbers from this table: [url]"
   - "Create a CSV from this data table image: [url]"
   - "What are the key metrics shown? [url]"

5) Image Comparison
   - "Compare these two product images: [url1] [url2]"
   - "What's different between these screenshots? [url1] [url2]"
   - "Which design is better and why? [url1] [url2]"

Example URLs for testing:
- Charts: Use public chart images from financial sites
- Screenshots: Use any public screenshot or dashboard image
- Tables: Use images of data tables from reports
"""
