import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.v2.workflow import WorkflowRunResponse
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.utils.pprint import pprint_run_response
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow

# Define agents
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    role="Search the web for the latest news and trends",
)

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    mode="coordinate",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

# Define steps
research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)

content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    storage=SqliteStorage(
        table_name="workflow_v2_bg",
        db_file="tmp/workflow_v2_bg.db",
        mode="workflow_v2",
    ),
    steps=[research_step, content_planning_step],
)


def get_status_value(status):
    """Helper function to get status value regardless of whether it's enum or string"""
    if isinstance(status, RunStatus):
        return status.value
    elif hasattr(status, "value"):
        return status.value
    return str(status)


def is_terminal_status(status_value: str) -> bool:
    """Check if status indicates workflow completion"""
    return status_value in [RunStatus.completed.value, RunStatus.error.value]


# Create and use workflow in background
if __name__ == "__main__":
    print("🚀 Starting Background Workflow Execution")
    
    # Start background execution - returns immediately
    start_time = time.time()
    bg_response = content_creation_workflow.run(
        message="AI trends in 2024", 
        background=True
    )
    
    print(f"⚡ Background execution started in {time.time() - start_time:.2f}s")
    print(f"📝 Run ID: {bg_response.run_id}")
    print(f"📊 Status: {get_status_value(bg_response.status)}")
    
    # Poll until completion
    print(f"\n🔄 Polling every 10 seconds until completion...")
    
    poll_count = 0
    while True:
        poll_count += 1
        time.sleep(10)  # Poll every 10 seconds
        
        # Get current status from database
        response = content_creation_workflow.poll(bg_response.run_id)
        
        if response:
            current_status = get_status_value(response.status)
            print(f"   Poll #{poll_count}: {current_status}")
            
            # Check if completed
            if is_terminal_status(current_status):
                print(f"\n✅ Workflow completed with status: {current_status}")
                break
        else:
            print(f"   Poll #{poll_count}: No response")
        
        # Safety limit
        if poll_count > 50:
            print(f"⏰ Timeout after {poll_count} attempts")
            break
    
    # Print final response using pprint
    if response and is_terminal_status(get_status_value(response.status)):
        print(f"\n📄 Final Response:")
        print("=" * 50)
        pprint_run_response(response, markdown=True)
    else:
        print(f"\n❌ Failed to get final response")