from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.v2.task import Task, TaskInput, TaskOutput
from agno.workflow.v2.workflow import Workflow

# Define agents
blog_analyzer = Agent(
    name="Blog Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
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


# Updated custom execution functions that work with TaskInput
def custom_blog_analysis_function(task_input: TaskInput) -> TaskOutput:
    """
    Custom function that does preprocessing, calls an agent, and does postprocessing
    """
    query = task_input.get_primary_input()

    # Custom preprocessing
    print(f"🔍 Starting custom blog analysis for: {query}")

    # Add custom context and formatting
    enhanced_query = f"""
        BLOG ANALYSIS REQUEST:
        Topic: {query}
        
        Please provide:
        1. Key themes and trends
        2. Target audience insights  
        3. Content opportunities
        4. SEO considerations
        
        Additional context from previous tasks:
        {task_input.previous_outputs if task_input.previous_outputs else "No previous context"}
    """

    # Call the agent with enhanced input
    try:
        response = blog_analyzer.run(enhanced_query)

        # Custom postprocessing
        enhanced_content = f"""
            ## Custom Blog Analysis Results

            **Original Query:** {query}

            **Analysis:**
            {response.content}

            **Custom Insights:**
            - Analysis completed with enhanced context
            - Ready for next stage processing
            - Confidence level: High
        """.strip()

        # Return TaskOutput with enhanced response
        return TaskOutput(
            content=enhanced_content,
            response=response,
            data={"analysis_type": "custom", "confidence": "high"},
            metadata={
                "function_name": "custom_blog_analysis_function",
                "preprocessing": True,
                "postprocessing": True,
            },
        )

    except Exception as e:
        return TaskOutput(
            content=f"Custom blog analysis failed: {str(e)}",
            metadata={"error": True, "function_name": "custom_blog_analysis_function"},
        )


def custom_team_research_function(task_input: TaskInput) -> TaskOutput:
    """
    Custom function that coordinates team execution with custom logic
    """
    query = task_input.get_primary_input()

    print(f"🔬 Starting custom team research for: {query}")
    print(f"Previous outputs available: {bool(task_input.previous_outputs)}")

    # Get the output from the previous task
    previous_analysis = ""
    if task_input.previous_outputs:
        # Try different keys to get previous content
        previous_analysis = (
            task_input.previous_outputs.get("custom_analysis", "")
            or task_input.previous_outputs.get("output", "")
            or task_input.previous_outputs.get("result", "")
        )

    # Create enhanced team prompt
    team_prompt = f"""
        RESEARCH COORDINATION REQUEST:
        
        Primary Topic: {query}
        
        Previous Analysis: {previous_analysis[:500] if previous_analysis else "No previous analysis"}
        
        Team Mission:
        1. Build upon the previous analysis
        2. Conduct deeper research on the topic
        3. Validate and expand findings
        4. Provide actionable recommendations
        
        Please coordinate effectively and provide a unified research report.
    """

    try:
        response = research_team.run(team_prompt)

        enhanced_content = f"""
            ## Custom Team Research Report

            **Research Topic:** {query}

            **Previous Analysis Integration:** {"✓ Integrated" if previous_analysis else "✗ No previous context"}

            **Team Coordination Results:**
            {response.content}

            **Custom Team Insights:**
            - Multi-agent coordination completed
            - Cross-validated findings included
            - Ready for strategic planning phase
        """.strip()

        return TaskOutput(
            content=enhanced_content,
            response=response,
            data={
                "research_type": "team_coordination",
                "integration": bool(previous_analysis),
            },
            metadata={
                "function_name": "custom_team_research_function",
                "team_coordination": True,
                "previous_context": bool(previous_analysis),
            },
        )

    except Exception as e:
        return TaskOutput(
            content=f"Custom team research failed: {str(e)}",
            metadata={"error": True, "function_name": "custom_team_research_function"},
        )


def custom_content_planning_function(task_input: TaskInput) -> TaskOutput:
    """
    Custom function that does intelligent content planning with context awareness
    """
    query = task_input.get_primary_input()

    print(f"📝 Starting custom content planning for: {query}")
    print(f"Previous outputs available: {bool(task_input.previous_outputs)}")

    # Get the output from the previous task
    previous_research = ""
    if task_input.previous_outputs:
        # Try different keys to get previous content
        previous_research = (
            task_input.previous_outputs.get("custom_research", "")
            or task_input.previous_outputs.get("output", "")
            or task_input.previous_outputs.get("result", "")
        )

    # Create intelligent planning prompt
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:
        
        Core Topic: {query}
        
        Research Foundation: {previous_research[:500] if previous_research else "No research foundation"}
        
        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies
        
        Please create a detailed, actionable content plan.
    """

    try:
        response = content_planner.run(planning_prompt)

        enhanced_content = f"""
            ## Strategic Content Plan

            **Planning Topic:** {query}

            **Research Integration:** {"✓ Research-based" if previous_research else "✗ No research foundation"}

            **Content Strategy:**
            {response.content}

            **Custom Planning Enhancements:**
            - Research Integration: {"High" if previous_research else "Baseline"}
            - Strategic Alignment: Optimized for multi-channel distribution
            - Execution Ready: Detailed action items included
        """.strip()

        return TaskOutput(
            content=enhanced_content,
            response=response,
            data={
                "planning_type": "strategic",
                "research_integration": bool(previous_research),
            },
            metadata={
                "function_name": "custom_content_planning_function",
                "strategic_planning": True,
                "research_based": bool(previous_research),
            },
        )

    except Exception as e:
        return TaskOutput(
            content=f"Custom content planning failed: {str(e)}",
            metadata={
                "error": True,
                "function_name": "custom_content_planning_function",
            },
        )


# Define tasks using different executor types
custom_analysis_task = Task(
    name="custom_analysis",
    execution_function=custom_blog_analysis_function,  # Custom function with agent
    description="Custom blog analysis with preprocessing and postprocessing",
)

custom_research_task = Task(
    name="custom_research",
    execution_function=custom_team_research_function,  # Custom function with team
    description="Custom team research with coordination logic",
)

custom_planning_task = Task(
    name="custom_planning",
    execution_function=custom_content_planning_function,  # Custom function with agent
    description="Custom content planning with context integration",
)

# Define and use examples
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation with custom execution options",
        storage=SqliteStorage(
            table_name="workflow_v2",
            db_file="tmp/workflow_v2.db",
            mode="workflow_v2",
        ),
        tasks=[custom_analysis_task, custom_research_task, custom_planning_task],
    )
    print("=== Custom Sequence (Custom Execution Functions) ===")
    try:
        content_creation_workflow.print_response(
            query="AI trends in 2024",
            markdown=True,
        )
    except Exception as e:
        print(f"Custom sequence failed: {e}")

    print("\n" + "=" * 60 + "\n")
