"""
Workflow - Step-Based Agentic Pipeline
========================================
Build a multi-step pipeline where steps execute in a defined order.

Key concepts:
- Workflow: Orchestrates steps in sequence, with branching and parallelism
- Step: A single unit of work, backed by an Agent, Team, or custom function
- Parallel: Run multiple steps concurrently
- Condition: Branch based on previous step output
- StepInput: Carries the original input + all previous step outputs
- StepOutput: What a step returns (content, stop flag, success flag)
- session_state: Persistent state across steps (saved to db)

Example prompts to try:
- "Latest developments in AI agents and autonomous systems"
- "The impact of climate change on global food production"
- "History and future of space exploration"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools
from agno.workflow import (
    Condition,
    Parallel,
    Step,
    StepInput,
    StepOutput,
    Workflow,
)
from db import gemini_agents_db

# ---------------------------------------------------------------------------
# Agents: each handles one stage of the pipeline
# ---------------------------------------------------------------------------
web_researcher = Agent(
    name="Web Researcher",
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions="""\
You are a web researcher. Search for the latest information on the given topic.

## Rules

- Find recent, credible sources
- Include key facts, statistics, and expert opinions
- Cite your sources
- No emojis\
""",
    add_datetime_to_context=True,
)

deep_researcher = Agent(
    name="Deep Researcher",
    model=Gemini(id="gemini-3-flash-preview"),
    tools=[WebSearchTools()],
    instructions="""\
You are a deep researcher. Search extensively for background context,
historical data, and expert analysis on the given topic.

## Rules

- Go beyond surface-level information
- Find contrasting viewpoints
- Include historical context and trends
- No emojis\
""",
    add_datetime_to_context=True,
)

analyst = Agent(
    name="Analyst",
    model=Gemini(id="gemini-3.1-pro-preview"),
    instructions="""\
You are a senior analyst. Synthesize research from multiple sources
into a clear, structured analysis.

## Rules

- Identify key themes and patterns across sources
- Highlight areas of agreement and disagreement
- Draw evidence-based conclusions
- Structure with clear sections and headers
- No emojis\
""",
)

report_writer = Agent(
    name="Report Writer",
    model=Gemini(id="gemini-3.1-pro-preview"),
    instructions="""\
You are a report writer. Transform analysis into a polished,
publication-ready report.

## Rules

- Write a compelling introduction that hooks the reader
- Use clear, accessible language
- Include an executive summary at the top
- End with key takeaways and future outlook
- No emojis\
""",
)

fact_checker = Agent(
    name="Fact Checker",
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions="""\
You are a fact-checker. Verify the factual claims in the report.

## Rules

- Check every statistic, date, and named claim
- Search for primary sources
- Flag anything unverified as [UNVERIFIED]
- Provide the corrected report with a verification summary at the end
- No emojis\
""",
)


# ---------------------------------------------------------------------------
# Custom step functions
# ---------------------------------------------------------------------------
def quality_gate(step_input: StepInput) -> StepOutput:
    """Check that the analysis has enough substance to proceed."""
    content = str(step_input.previous_step_content or "")
    if len(content) < 200:
        return StepOutput(
            content="Quality gate failed: analysis too short. Stopping pipeline.",
            stop=True,
            success=False,
        )
    return StepOutput(
        content=content,
        success=True,
    )


def needs_fact_check(step_input: StepInput) -> bool:
    """Decide whether the report needs fact-checking."""
    content = str(step_input.previous_step_content or "").lower()
    indicators = [
        "study",
        "research",
        "percent",
        "%",
        "million",
        "billion",
        "according",
    ]
    return any(indicator in content for indicator in indicators)


# ---------------------------------------------------------------------------
# Build Workflow
# ---------------------------------------------------------------------------
research_pipeline = Workflow(
    id="gemini-research-pipeline",
    name="Research Pipeline",
    description="Research-to-publication pipeline: parallel research, analysis, quality gate, writing, and conditional fact-checking.",
    db=gemini_agents_db,
    steps=[
        # Step 1: Research in parallel (two agents search simultaneously)
        Parallel(
            "Research",
            Step(name="web_research", agent=web_researcher),
            Step(name="deep_research", agent=deep_researcher),
        ),
        # Step 2: Analyst synthesizes all research
        Step(name="analysis", agent=analyst),
        # Step 3: Quality gate (stop early if analysis is too thin)
        Step(name="quality_gate", executor=quality_gate),
        # Step 4: Writer produces the final report
        Step(name="report", agent=report_writer),
        # Step 5: Conditionally fact-check (only if the report has factual claims)
        Condition(
            name="fact_check_gate",
            evaluator=needs_fact_check,
            steps=[Step(name="fact_check", agent=fact_checker)],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_pipeline.print_response(
        "Latest developments in AI agents and autonomous systems",
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Workflow vs Team:

- Team (step 19): Leader LLM decides who to delegate to at runtime.
  Flexible but less predictable. Best for creative, open-ended tasks.

- Workflow (this step): Steps execute in a defined order with explicit
  branching logic. Predictable and repeatable. Best for pipelines.

Workflow building blocks:

1. Step(agent=...)            Run an agent
2. Step(team=...)             Run a team
3. Step(executor=fn)          Run a custom function
4. Parallel(step1, step2)     Run steps concurrently
5. Condition(evaluator, ...)  Branch based on logic
6. Loop(steps, ...)           Repeat until done
7. Router(choices, selector)  Dynamically pick which step to run

Accessing previous step outputs in a custom executor:

    def my_step(step_input: StepInput) -> StepOutput:
        # Original workflow input
        original = step_input.input

        # Output from the immediately preceding step
        last = step_input.previous_step_content

        # Output from a specific named step
        research = step_input.get_step_content("web_research")

        # All previous outputs concatenated
        everything = step_input.get_all_previous_content()

        return StepOutput(content="done")

Early stopping from any step:

    return StepOutput(content="Stopping.", stop=True)
"""
