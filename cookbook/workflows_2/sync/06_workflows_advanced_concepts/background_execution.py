from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.googlesearch import GoogleSearchTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow
from agno.run.base import RunStatus
import time

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
    tools=[GoogleSearchTools()],
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
        table_name="workflow_v2_clean",
        db_file="tmp/workflow_v2_clean.db",
        mode="workflow_v2",
    ),
    steps=[research_step, content_planning_step],
)

def get_status_value(status):
    """Helper function to get status value regardless of whether it's enum or string"""
    if isinstance(status, RunStatus):
        return status.value
    elif hasattr(status, 'value'):
        return status.value
    return str(status)

def is_terminal_status(status_value: str) -> bool:
    """Check if status indicates workflow completion"""
    return status_value in [RunStatus.completed.value, RunStatus.error.value]

if __name__ == "__main__":
    print("🚀 Starting Background Workflow Test (Cleaned Up)")
    
    # Example 1: Background execution (non-blocking)
    start_time = time.time()
    
    # Start background execution - returns immediately with PENDING status
    bg_response = content_creation_workflow.run(
        message="Machine Learning advances in 2024",
        background=True
    )
    
    immediate_time = time.time()
    print(f"⚡ Background execution started in {immediate_time - start_time:.2f}s")
    print(f"📝 Run ID: {bg_response.run_id}")
    print(f"📊 Initial Status: {get_status_value(bg_response.status)}")
    print(f"📄 Initial Content: {bg_response.content}")
    
    # Example 2: Polling for completion using WorkflowRunResponse
    print(f"\n🔄 Polling for completion every 10 seconds...")
    poll_count = 0
    last_status = None
    
    while True:
        poll_count += 1
        time.sleep(10)  # Poll every 10 seconds
        
        # Get WorkflowRunResponse from database (source of truth)
        response = content_creation_workflow.poll(bg_response.run_id)
        
        if response:
            current_status = get_status_value(response.status)
            print(f"   Poll {poll_count}: Status = {current_status}")
            
            # Track status changes
            if current_status != last_status:
                print(f"   📊 Status changed: {last_status} → {current_status}")
                last_status = current_status
            
            # Check if workflow completed (terminal status)
            if is_terminal_status(current_status):
                print(f"\n✅ Workflow completed with status: {current_status}")
                print(f"📄 Content: {response.content[:200]}...")
                
                # If completed successfully, show full content length
                if current_status == RunStatus.completed.value and len(response.content) > 200:
                    print(f"📄 Full content length: {len(response.content)} characters")
                break
                
        else:
            print(f"   Poll {poll_count}: No response from database")
        
        # Safety limit
        if poll_count > 50:
            print(f"⏰ Polling timeout after {poll_count} attempts")
            break
    
    # Example 3: Final registry status
    print(f"\n🔧 Final background runs status:")
    background_runs = Workflow.get_background_runs()
    if background_runs:
        for run_id, run_info in background_runs.items():
            print(f"   Run {run_id}: Alive={run_info.get('is_alive', False)}")
    else:
        print("   No active background runs")
    
    print(f"\n=== Background Execution Demo Complete ===")