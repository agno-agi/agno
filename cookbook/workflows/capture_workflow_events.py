from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.googlesearch import GoogleSearchTools
from agno.workflow.v2.sequence import Sequence
from agno.workflow.v2.task import Task
from agno.workflow.v2.workflow import Workflow
from agno.run.v2.workflow import (
    WorkflowStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    TaskErrorEvent,
)

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
    """Print workflow events in a clean format as they happen using new event classes"""

    print(f"\n🚀 Starting Workflow: {workflow.name}")
    print(f"📝 Query: {query}")
    if sequence_name:
        print(f"🔄 Sequence: {sequence_name}")
    print("=" * 60)

    try:
        for event in workflow.run(query=query, sequence_name=sequence_name):
            if isinstance(event, WorkflowStartedEvent):
                print(f"✅ WORKFLOW STARTED")
                print(f"   └─ Sequence: {event.sequence_name}")
                if event.content:
                    preview = truncate_content(str(event.content))
                    print(f"   └─ Content: {preview}")

            elif isinstance(event, TaskStartedEvent):
                task_name = event.task_name or "Unknown"
                task_index = (event.task_index or 0) + 1
                print(f"🔄 TASK {task_index} STARTED: {task_name}")
                if event.content:
                    preview = truncate_content(str(event.content))
                    print(f"   └─ Content: {preview}")

            elif isinstance(event, TaskCompletedEvent):
                task_name = event.task_name or "Unknown"
                task_index = (event.task_index or 0) + 1
                print(f"✅ TASK {task_index} COMPLETED: {task_name}")
                if event.content:
                    preview = truncate_content(str(event.content))
                    print(f"   └─ Content: {preview}")

                # Show additional task completion details
                if event.task_responses:
                    print(
                        f"   └─ Task Responses: {len(event.task_responses)} response(s)")
                if event.images:
                    print(f"   └─ Images: {len(event.images)} image(s)")
                if event.videos:
                    print(f"   └─ Videos: {len(event.videos)} video(s)")
                if event.audio:
                    print(f"   └─ Audio: {len(event.audio)} audio file(s)")

            elif isinstance(event, WorkflowCompletedEvent):
                print(f"🎉 WORKFLOW COMPLETED")
                if event.extra_data:
                    status = event.extra_data.get("status", "Unknown")
                    total_tasks = event.extra_data.get("total_tasks", 0)
                    print(f"   └─ Status: {status}")
                    print(f"   └─ Total Tasks: {total_tasks}")
                if event.content:
                    preview = truncate_content(str(event.content))
                    print(f"   └─ Content: {preview}")
                if event.task_responses:
                    print(
                        f"   └─ Total Task Responses: {len(event.task_responses)}")

            elif isinstance(event, TaskErrorEvent):
                task_name = event.task_name or "Unknown"
                task_index = (event.task_index or 0) + 1
                print(f"❌ TASK {task_index} ERROR: {task_name}")
                print(f"   └─ Error: {event.error}")

            elif isinstance(event, WorkflowErrorEvent):
                print(f"❌ WORKFLOW ERROR")
                print(f"   └─ Error: {event.error}")
                if event.content:
                    preview = truncate_content(str(event.content))
                    print(f"   └─ Content: {preview}")

        print("=" * 60)
        print("✨ Workflow execution finished!")

    except Exception as e:
        print(f"❌ EXECUTION FAILED: {str(e)}")
        print("=" * 60)


def print_workflow_events_detailed(workflow: Workflow, query: str, sequence_name: str = None):
    """Print workflow events with more detailed information"""

    print(f"\n🚀 Starting Detailed Workflow: {workflow.name}")
    print(f"📝 Query: {query}")
    if sequence_name:
        print(f"🔄 Sequence: {sequence_name}")
    print("=" * 80)

    event_count = 0
    task_count = 0

    try:
        for event in workflow.run(query=query, sequence_name=sequence_name):
            event_count += 1

            print(f"\n[Event #{event_count}] {event.__class__.__name__}")
            print(f"  ├─ Event Type: {event.event}")
            print(f"  ├─ Run ID: {event.run_id}")
            print(f"  ├─ Workflow: {event.workflow_name}")
            print(f"  ├─ Sequence: {event.sequence_name}")

            if isinstance(event, (TaskStartedEvent, TaskCompletedEvent, TaskErrorEvent)):
                task_count += 1
                print(
                    f"  ├─ Task: {event.task_name} (Index: {event.task_index})")

            if event.content:
                preview = truncate_content(str(event.content), max_length=100)
                print(f"  ├─ Content: {preview}")

            if isinstance(event, TaskCompletedEvent):
                if event.task_responses:
                    print(f"  ├─ Task Responses: {len(event.task_responses)}")
                if event.messages:
                    print(f"  ├─ Messages: {len(event.messages)}")
                if event.metrics:
                    print(f"  ├─ Metrics: {list(event.metrics.keys())}")

            if isinstance(event, WorkflowCompletedEvent):
                if event.extra_data:
                    print(
                        f"  ├─ Extra Data Keys: {list(event.extra_data.keys())}")
                if event.task_responses:
                    print(
                        f"  ├─ Total Task Responses: {len(event.task_responses)}")

            if isinstance(event, (TaskErrorEvent, WorkflowErrorEvent)):
                print(f"  ├─ Error: {event.error}")

            print(f"  └─ Timestamp: {event.created_at}")

        print("\n" + "=" * 80)
        print(f"✨ Workflow execution finished!")
        print(f"📊 Total Events: {event_count}")
        print(f"🔧 Tasks Processed: {task_count}")

    except Exception as e:
        print(f"❌ EXECUTION FAILED: {str(e)}")
        print("=" * 80)


if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        storage=SqliteStorage(
            table_name="workflow_v2", db_file="tmp/workflow_v2.db", mode="workflow_v2"
        ),
        sequences=[research_sequence, content_creation_sequence],
    )

    print("=== Simple Event Tracking (New Event Classes) ===")
    print_workflow_events(
        workflow=content_creation_workflow,
        query="AI trends in 2024",
        sequence_name="research_sequence",
    )

    print("\n\n=== Detailed Event Tracking ===")
    print_workflow_events_detailed(
        workflow=content_creation_workflow,
        query="Machine Learning best practices",
        sequence_name="content_creation",
    )
