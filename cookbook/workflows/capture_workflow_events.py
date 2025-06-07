from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.workflow import WorkflowRunEvent
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.googlesearch import GoogleSearchTools
from agno.workflow.v2.sequence import Sequence
from agno.workflow.v2.task import Task
from agno.workflow.v2.trigger import ManualTrigger
from agno.workflow.v2.workflow import Workflow

# Define agents
blog_analyzer = Agent(
    name="Blog Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleSearchTools()],
    instructions="Extract key insights and content from blog posts",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Create engaging social media content plans based on analysis",
)

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    mode="coordinate",
    members=[blog_analyzer, content_planner],
    instructions="Analyze content and create comprehensive social media strategy",
)

# Define tasks with consistent query-based input
analyze_blog_task = Task(
    name="analyze_blog",
    agent=blog_analyzer,
    description="Analyze the provided topic and extract key insights",
)

plan_content_task = Task(
    name="plan_content",
    agent=content_planner,
    description="Create social media content plan based on the research topic and previous analysis",
)

research_task = Task(
    name="research_content",
    team=research_team,
    description="Deep research and analysis of content",
)

# Define sequences
content_creation_sequence = Sequence(
    name="content_creation",
    description="End-to-end content creation from blog to social media",
    tasks=[analyze_blog_task],
)

research_sequence = Sequence(
    name="research_sequence",
    description="Deep research workflow using teams",
    tasks=[research_task, plan_content_task],
)


def truncate_content(content: str, max_length: int = 50) -> str:
    """Truncate content to specified length with ellipsis"""
    if not content:
        return ""

    # Clean up the content - remove extra whitespace and newlines
    cleaned = " ".join(content.strip().split())

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[:max_length] + "..."


def print_workflow_events(workflow: Workflow, query: str, sequence_name: str = None):
    """Print workflow events in a clean format as they happen"""

    print(f"\n🚀 Starting Workflow: {workflow.name}")
    print(f"📝 Query: {query}")
    if sequence_name:
        print(f"🔄 Sequence: {sequence_name}")
    print("=" * 60)

    try:
        for response in workflow.run(query=query, sequence_name=sequence_name):
            if response.event == WorkflowRunEvent.workflow_started:
                print(f"✅ WORKFLOW STARTED")
                print(f"   └─ Sequence: {response.sequence_name}")
                if response.content:
                    preview = truncate_content(str(response.content))
                    print(f"   └─ Content: {preview}")

            elif response.event == WorkflowRunEvent.task_started:
                task_name = response.task_name or "Unknown"
                task_index = (response.task_index or 0) + 1
                print(f"🔄 TASK {task_index} STARTED: {task_name}")
                if response.content:
                    preview = truncate_content(str(response.content))
                    print(f"   └─ Content: {preview}")

            elif response.event == WorkflowRunEvent.task_completed:
                task_name = response.task_name or "Unknown"
                task_index = (response.task_index or 0) + 1
                print(f"✅ TASK {task_index} COMPLETED: {task_name}")
                if response.content:
                    preview = truncate_content(str(response.content))
                    print(f"   └─ Content: {preview}")

            elif response.event == WorkflowRunEvent.workflow_completed:
                print(f"🎉 WORKFLOW COMPLETED")
                if response.extra_data:
                    status = response.extra_data.get("status", "Unknown")
                    total_tasks = response.extra_data.get("total_tasks", 0)
                    print(f"   └─ Status: {status}")
                    print(f"   └─ Total Tasks: {total_tasks}")
                if response.content:
                    preview = truncate_content(str(response.content))
                    print(f"   └─ Content: {preview}")

            elif response.event == WorkflowRunEvent.workflow_error:
                print(f"❌ WORKFLOW ERROR")
                print(f"   └─ Error: {response.content}")

        print("=" * 60)
        print("✨ Workflow execution finished!")

    except Exception as e:
        print(f"❌ EXECUTION FAILED: {str(e)}")
        print("=" * 60)


if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        trigger=ManualTrigger(),
        storage=SqliteStorage(
            table_name="workflow_v2", db_file="tmp/workflow_v2.db", mode="workflow_v2"
        ),
        sequences=[research_sequence, content_creation_sequence],
    )

    print("=== Simple Event Tracking ===")
    print_workflow_events(
        workflow=content_creation_workflow,
        query="AI trends in 2024",
        sequence_name="research_sequence",
    )
