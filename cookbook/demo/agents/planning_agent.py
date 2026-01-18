"""
Planning Agent - An autonomous agent that breaks down complex goals into steps and executes them.

This agent is designed to handle complex, multi-step tasks. It can:
- Analyze goals and decompose them into actionable steps
- Execute steps sequentially with verification
- Research information needed for each step
- Self-correct when steps fail
- Produce comprehensive final outputs

Example queries:
- "Build a complete market analysis of the electric vehicle industry"
- "Create a competitor analysis for OpenAI vs Anthropic"
- "Research AI agents and create an investment thesis"
- "Analyze the semiconductor market and identify top 3 investment opportunities"
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.parallel import ParallelTools
from agno.tools.python import PythonTools
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Setup working directory for any code execution
# ============================================================================
WORK_DIR = Path(__file__).parent.parent / "workspace"
WORK_DIR.mkdir(exist_ok=True)

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Planning Agent - an autonomous AI that tackles complex goals by breaking them down
    into clear steps and executing each one systematically until the goal is achieved.
    """)

instructions = dedent("""\
    You are an expert strategic planner and executor. Your job is to take complex, open-ended goals
    and systematically work through them to produce high-quality results.

    PLANNING PHASE:
    When you receive a goal, first use the reasoning tools to:
    1. **Understand the Goal**: Clarify what success looks like
    2. **Decompose**: Break it into 3-7 concrete, actionable steps
    3. **Identify Dependencies**: Note which steps depend on others
    4. **Anticipate Challenges**: Consider what might go wrong

    EXECUTION PHASE:
    For each step:
    1. **Announce**: State which step you're working on
    2. **Execute**: Use appropriate tools (research, code, analysis)
    3. **Verify**: Check that the step produced the expected output
    4. **Adapt**: If something fails, adjust your approach and retry

    TOOLS AVAILABLE:
    - **ReasoningTools**: Use `think` for planning and `analyze` for evaluation
    - **ParallelTools**: Use for web research, gathering information
    - **PythonTools**: Use for data processing, calculations, file creation

    WORKFLOW EXAMPLE:
    Goal: "Create a market analysis of the EV industry"

    Step 1: Research current EV market size and growth
    - Use parallel_search to find market data
    - Extract key statistics

    Step 2: Identify major players and market share
    - Research Tesla, BYD, VW, etc.
    - Create comparison data

    Step 3: Analyze trends and drivers
    - Government policies
    - Battery technology
    - Consumer preferences

    Step 4: Assess challenges and risks
    - Supply chain issues
    - Competition from traditional automakers
    - Infrastructure gaps

    Step 5: Synthesize into final report
    - Compile all findings
    - Create executive summary
    - List key takeaways

    OUTPUT FORMAT:
    - Start with a brief plan overview (the steps you'll take)
    - Show progress as you complete each step
    - End with a comprehensive, well-structured deliverable
    - Use markdown formatting: headers, bullet points, tables
    - Include sources and data citations where relevant

    QUALITY STANDARDS:
    - Be thorough but efficient
    - Prioritize accuracy over speed
    - Cite sources when making claims
    - Acknowledge limitations and uncertainties
    - Produce actionable insights, not just information
    """)

# ============================================================================
# Create the Agent
# ============================================================================
planning_agent = Agent(
    name="Planning Agent",
    role="Break down complex goals into steps and execute them autonomously",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        ReasoningTools(add_instructions=True),
        ParallelTools(enable_search=True, enable_extract=True),
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
1) Market Analysis
   - "Build a complete market analysis of the electric vehicle industry"
   - "Analyze the cloud computing market: AWS vs Azure vs GCP"

2) Investment Research
   - "Create an investment thesis for NVIDIA"
   - "Should I invest in AI stocks? Build a comprehensive analysis"

3) Competitor Analysis
   - "Create a competitor analysis for OpenAI vs Anthropic vs Google"
   - "Analyze the CRM market: Salesforce vs HubSpot vs others"

4) Industry Research
   - "Research the AI agent landscape in 2025 and identify key trends"
   - "Analyze the fintech industry: opportunities and risks"

5) Strategic Planning
   - "Create a go-to-market strategy for a new AI product"
   - "Build a business case for adopting AI agents in enterprise"
"""
