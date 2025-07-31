from typing import List

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow.v2 import Loop, Step, Workflow
from agno.workflow.v2.types import StepOutput

# Create agents for research
research_agent = Agent(
    name="Research Agent",
    role="Research specialist",
    tools=[HackerNewsTools(), DuckDuckGoTools()],
    instructions="You are a research specialist. Research the given topic thoroughly.",
    markdown=True,
)

content_agent = Agent(
    name="Content Agent",
    role="Content creator",
    instructions="You are a content creator. Create engaging content based on research.",
    markdown=True,
)

# Create research steps
research_hackernews_step = Step(
    name="Research HackerNews",
    agent=research_agent,
    description="Research trending topics on HackerNews",
)

research_web_step = Step(
    name="Research Web",
    agent=research_agent,
    description="Research additional information from web sources",
)

content_step = Step(
    name="Create Content",
    agent=content_agent,
    description="Create content based on research findings",
)

# End condition function


def research_evaluator(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if research results are sufficient
    Returns True to break the loop, False to continue
    """
    # Check if we have good research results
    if not outputs:
        print("❌ Research evaluation: No outputs found")
        return False

    # Simple check - if any output contains substantial content, we're good
    for i, output in enumerate(outputs):
        if output.content and len(output.content) > 200:
            print(
                f"✅ Research evaluation passed - Step {i + 1} found substantial content ({len(output.content)} chars)"
            )
            return True

    print("❌ Research evaluation failed - need more substantial research")
    print(
        f"   Found {len(outputs)} outputs with lengths: {[len(o.content) if o.content else 0 for o in outputs]}"
    )
    return False


# Create workflow with loop
workflow = Workflow(
    name="Research and Content Workflow",
    description="Research topics in a loop until conditions are met, then create content",
    debug_mode=True,  # Enable debug mode for workflow
    steps=[
        Loop(
            name="Research Loop",
            steps=[research_hackernews_step, research_web_step],
            end_condition=research_evaluator,
            max_iterations=3,  # Maximum 3 iterations
        ),
        content_step,
    ],
)

if __name__ == "__main__":
    print("🧪 Testing Research and Content Workflow with Debug Mode")
    print("=" * 60)
    print("🔍 Topic: Latest trends in AI and machine learning")
    print("🌊 Streaming: Enabled with intermediate steps")
    print()

    print("🚀 Starting workflow execution...")
    print("-" * 40)

    # Collect all chunks to build the final response
    all_chunks = []

    for chunk in workflow.run(
        message="Research the latest trends in AI and machine learning, then create a summary",
        stream=True,
        stream_intermediate_steps=True,
    ):
        all_chunks.append(chunk)

    # Print the final results
    print("\n" + "=" * 60)
    print("📊 FINAL WORKFLOW EXECUTION RESULTS")
    print("=" * 60)

    if all_chunks:
        # Use the workflow's run_response which should be the complete response
        if hasattr(workflow, "run_response") and workflow.run_response:
            pprint_run_response(workflow.run_response, markdown=True, show_time=True)
        else:
            # Fallback: just print the last chunk content if it exists
            final_chunk = all_chunks[-1]
            if hasattr(final_chunk, "content") and final_chunk.content:
                print("📝 Final Content:")
                print(final_chunk.content)
            else:
                print("❌ No final content found")
                print(f"Last chunk type: {type(final_chunk).__name__}")
    else:
        print("❌ No chunks received")
