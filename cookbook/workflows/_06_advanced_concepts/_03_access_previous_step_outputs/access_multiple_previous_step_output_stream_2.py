"""
This example shows how to access the output of multiple previous steps in a workflow.

The workflow is defined as a list of steps, where each step is directly an agent or a function.
We dont use Step objects in this example.
"""

from agno.agent.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# Define the research agents
hackernews_agent = Agent(
    instructions="You are a researcher specializing in finding the latest tech news and discussions from Hacker News. Focus on startup trends, programming topics, and tech industry insights.",
    tools=[HackerNewsTools()],
)

web_agent = Agent(
    instructions="You are a comprehensive web researcher. Search across multiple sources including news sites, blogs, and official documentation to gather detailed information.",
    tools=[DuckDuckGoTools()],
)

reasoning_agent = Agent(
    instructions="You are an expert analyst who creates comprehensive reports by analyzing and synthesizing information from multiple sources. Create well-structured, insightful reports.",
)


# Custom function step that has access to ALL previous step outputs
def create_comprehensive_report(step_input: StepInput) -> StepOutput:
    """
    Custom function that creates a report using data from multiple previous steps.
    This function has access to ALL previous step outputs and the original workflow message.
    """

    # Access original workflow input
    original_topic = step_input.input or ""

    # Access specific step outputs by name
    hackernews_data = step_input.get_step_content("step_1") or ""
    web_data = step_input.get_step_content("step_2") or ""

    # Or access ALL previous content
    _ = step_input.get_all_previous_content()

    # Create a comprehensive report combining all sources
    report = f"""
        # Comprehensive Research Report: {original_topic}

        ## Executive Summary
        Based on research from HackerNews and web sources, here's a comprehensive analysis of {original_topic}.

        ## HackerNews Insights
        {hackernews_data[:500]}...

        ## Web Research Findings  
        {web_data[:500]}...
    """

    return StepOutput(content=report.strip(), success=True)


# Custom function to print the comprehensive report
def print_final_report(step_input: StepInput) -> StepOutput:
    """
    Custom function that receives the comprehensive report and prints it.
    """

    # Get the output from the comprehensive_report step
    comprehensive_report = step_input.get_step_content("create_comprehensive_report")

    # Print the report
    print("=" * 80)
    print("FINAL COMPREHENSIVE REPORT")
    print("=" * 80)
    print(comprehensive_report)
    print("=" * 80)

    # Also print all previous step outputs for debugging
    print("\nDEBUG: All previous step outputs:")
    if step_input.previous_step_outputs:
        for step_name, output in step_input.previous_step_outputs.items():
            print(f"- {step_name}: {len(str(output.content))} characters")

    return StepOutput(
        step_name="print_final_report",
        content=f"Printed comprehensive report ({len(comprehensive_report)} characters)",
        success=True,
    )


# Final reasoning step using reasoning agent
reasoning_step = Step(
    name="final_reasoning",
    agent=reasoning_agent,
    description="Apply reasoning to create final insights and recommendations",
)

workflow = Workflow(
    name="Enhanced Research Workflow",
    description="Multi-source research with custom data flow and reasoning",
    steps=[
        hackernews_agent,
        web_agent,
        create_comprehensive_report,  # Has access to both previous steps
        print_final_report,
    ],
)

if __name__ == "__main__":
    workflow.print_response(
        "Latest developments in artificial intelligence and machine learning",
    )
