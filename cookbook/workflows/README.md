# Agno Workflows 2.0 - Developer Guide

Welcome to **Agno Workflows 2.0** - the next generation of intelligent, flexible workflow orchestration. This guide covers all workflow patterns, from simple linear sequences to complex conditional logic with parallel execution.

## Table of Contents

- [Agno Workflows 2.0 - Developer Guide](#agno-workflows-20---developer-guide)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
    - [Key Features](#key-features)
  - [Core Concepts](#core-concepts)
    - [Building Blocks](#building-blocks)
    - [Atomic Units with Controlled Execution](#atomic-units-with-controlled-execution)
  - [Workflow Patterns](#workflow-patterns)
    - [1. Basic Sequential Workflows](#1-basic-sequential-workflows)
    - [2. `Workflows 1.0` type execution](#2-workflows-10-type-execution)
    - [3. Basic Step Based Execution](#3-basic-step-based-execution)
    - [4. Parallel Execution](#4-parallel-execution)
    - [5. Conditional Steps](#5-conditional-steps)
    - [6. Loop/Iteration Workflows](#6-loopiteration-workflows)
    - [7. Condition-Based Branching](#7-condition-based-branching)
    - [8. Steps: Grouping a list of steps](#8-steps-grouping-a-list-of-steps)
      - [Steps with Router for Clean Branching](#steps-with-router-for-clean-branching)
    - [9. Complex Combinations](#9-complex-combinations)
  - [Advanced Features](#advanced-features)
    - [Early Stopping](#early-stopping)
    - [Access Multiple Previous Steps Output](#access-multiple-previous-steps-output)
    - [Event Storage and Filtering](#event-storage-and-filtering)
    - [Additional Data](#additional-data)
    - [Streaming Support](#streaming-support)
    - [Session State Management](#session-state-management)
    - [Background Execution](#background-execution)
    - [Structured Inputs](#structured-inputs)
  - [Best Practices](#best-practices)
    - [When to Use Each Pattern](#when-to-use-each-pattern)
  - [Migration from Workflows 1.0](#migration-from-workflows-10)
    - [Key Differences](#key-differences)
    - [Migration Steps](#migration-steps)

## Overview

Agno Workflows 2.0 provides a powerful, declarative way to orchestrate multi-step AI processes. Unlike traditional linear workflows, you can now create sophisticated branching logic, parallel execution, and dynamic routing based on content analysis.

![Workflows 2.0 flow](assets/workflows_flow.png)

### Key Features

- 🔄 **Flexible Execution**: Sequential, parallel, conditional, and loop-based execution
- 🎯 **Smart Routing**: Dynamic step selection based on content analysis
- 🔧 **Mixed Components**: Combine agents, teams, and functions seamlessly
- 💾 **State Management**: Share data across steps with session state
- 🌊 **Streaming Support**: Having support for event-based streamed information
- 📝 **Structured Inputs**: Type-safe inputs with Pydantic models

## Core Concepts

### Building Blocks

| Component | Purpose | Example Use Case |
|-----------|---------|------------------|
| **Step** | Basic execution unit | Single research task |
| **Agent** | AI assistant with specific role | Content writer, researcher |
| **Team** | Coordinated group of agents | Research team with specialists |
| **Function** | Custom Python logic | Data processing, API calls |
| **Parallel** | Concurrent execution | Multiple research streams |
| **Condition** | Conditional execution | Topic-specific processing |
| **Loop** | Iterative execution | Quality-driven research |
| **Router** | Dynamic routing | Content-based step selection |

### Atomic Units with Controlled Execution
The workflow system is built around the concept of atomic execution units in Agno- `Agents` and `Teams`, these are individual components that can work independently but gain enhanced capabilities when orchestrated together:
- **Agents**: Individual AI executors with specific capabilities and instructions
- **Teams**: Coordinated groups of agents working together on complex problems
- **Custom Python Functions**: Custom Python functions for specialized processing logic and full control

The beauty of this approach is that you maintain the full power and flexibility of each atomic unit while gaining sophisticated orchestration capabilities. Your agents and teams retain their individual characteristics, memory, and behavior patterns, but now operate within a structured workflow that provides:
- Sequential step execution with output chaining
- Session management and state persistence
- Error handling and retry mechanisms
- Streaming capabilities for real-time feedback

## Workflow Patterns

### 1. Basic Sequential Workflows

**When to use**: Linear processes where each step depends on the previous one.

**Example**: Research → Preprocess data in a function before next step → Content Creation

```python
from agno.workflow import Step, Workflow

def data_preprocessor(step_input):
    # Custom preprocessing logic

    # Or you can also run any agent/team over here itself
    # response = some_agent.run(...)
    return StepOutput(content=f"Processed: {step_input.input}") # <-- Now pass the agent/team response in content here

workflow = Workflow(
    name="Mixed Execution Pipeline",
    steps=[
        research_team,      # Team
        data_preprocessor,  # Function
        content_agent,      # Agent
    ]
)

workflow.print_response("Analyze the competitive landscape for fintech startups", markdown=True)
```

**See Examples**:
- [`sequence_of_functions_and_agents.py`](_01_basic_workflows/_01_sequence_of_steps/sync/sequence_of_functions_and_agents.py)
- [`sequence_of_functions_and_agents_stream.py`](_01_basic_workflows/_01_sequence_of_steps/sync/sequence_of_functions_and_agents_stream.py)


> **Note**: `StepInput` and `StepOutput` provides standardized interfaces for data flow between steps:
![Workflows Step IO](assets/step_io_flow.png)

> So if you make a custom function as an executor for a step, do make sure that the input and output types are compatible with the `StepInput` and `StepOutput` interfaces. This will ensure that your custom function can seamlessly integrate into the workflow system.

### 2. `Workflows 1.0` type execution

**Keep it Simple with Pure Python**: If you prefer the Workflows 1.0 approach or need maximum flexibility, you can still use a single Python function to handle everything. This approach gives you complete control over the execution flow while still benefiting from workflow features like storage, streaming, and session management.

Replace all the steps in the workflow with a single executable function where you can control everything.

```python
def custom_workflow_function(workflow: Workflow, execution_input: WorkflowExecutionInput):
    # Custom orchestration logic
    research_result = research_team.run(execution_input.message)
    analysis_result = analysis_agent.run(research_result.content)
    return f"Final: {analysis_result.content}"

workflow = Workflow(
    name="Function-Based Workflow",
    steps=custom_workflow_function  # Single function replaces all steps
)

workflow.print_response("Evaluate the market potential for quantum computing applications", markdown=True)
```

**See Examples**:
- [`function_instead_of_steps.py`](_01_basic_workflows/_03_function_instead_of_steps/sync/function_instead_of_steps.py) - Complete function-based workflow
- [`function_instead_of_steps_stream.py`](_01_basic_workflows/_03_function_instead_of_steps/sync/function_instead_of_steps_stream.py) - Streaming version

For migration to 2.0 refer to this section- [Migration from Workflows 1.0](#migration-from-workflows-10)

### 3. Basic Step Based Execution

**You can name your steps** for better logging and future support on the Agno platform:

```python
from agno.workflow import Step, Workflow

# Named steps for better tracking
workflow = Workflow(
    name="Content Creation Pipeline",
    steps=[
        Step(name="Research Phase", team=researcher),
        Step(name="Analysis Phase", executor=custom_function),
        Step(name="Writing Phase", agent=writer),
    ]
)

workflow.print_response(
    "AI trends in 2024",
    markdown=True,
)
```

**See Examples**:
- [`sequence_of_steps.py`](_01_basic_workflows/_01_sequence_of_steps/sync/sequence_of_steps.py)
- [`sequence_of_steps_stream.py`](_01_basic_workflows/_01_sequence_of_steps/sync/sequence_of_steps_stream.py)
- [`step_with_function.py`](_01_basic_workflows/_02_step_with_function/sync/step_with_function.py)
- [`step_with_function_stream.py`](_01_basic_workflows/_02_step_with_function/sync/step_with_function_stream.py)

### 4. Parallel Execution

**When to use**: Independent tasks that can run simultaneously to save time.

**Example**: Multiple research sources, parallel content creation

![Parallel Steps](assets/parallel_steps.png)

```python
from agno.workflow import Parallel, Step, Workflow

workflow = Workflow(
    name="Parallel Research Pipeline",
    steps=[
        Parallel(
            Step(name="HackerNews Research", agent=hn_researcher),
            Step(name="Web Research", agent=web_researcher),
            Step(name="Academic Research", agent=academic_researcher),
            name="Research Phase"
        ),
        Step(name="Synthesis", agent=synthesizer),
    ]
)

workflow.print_response("Write about the latest AI developments", markdown=True)
```

**See Examples**:
- [`parallel_steps_workflow.py`](_04_workflows_parallel_execution/sync/parallel_steps_workflow.py)
- [`parallel_steps_workflow_stream.py`](_04_workflows_parallel_execution/sync/parallel_steps_workflow_stream.py)

### 5. Conditional Steps

**When to use**: Conditional step execution based on business logic.

**Example**: Topic-specific research strategies, content type routing

![Condition Steps](assets/condition_steps.png)

```python
from agno.workflow import Condition, Step, Workflow

def is_tech_topic(step_input) -> bool:
    topic = step_input.input.lower()
    return any(keyword in topic for keyword in ["ai", "tech", "software"])

workflow = Workflow(
    name="Conditional Research",
    steps=[
        Condition(
            name="Tech Topic Check",
            evaluator=is_tech_topic,
            steps=[Step(name="Tech Research", agent=tech_researcher)]
        ),
        Step(name="General Analysis", agent=general_analyst),
    ]
)

workflow.print_response("Comprehensive analysis of AI and machine learning trends", markdown=True)
```

**See Examples**:
- [`condition_with_list_of_steps.py`](_02_workflows_conditional_execution/sync/condition_with_list_of_steps.py)
- [`condition_steps_workflow_stream.py`](_02_workflows_conditional_execution/sync/condition_steps_workflow_stream.py)

### 6. Loop/Iteration Workflows

**When to use**: Quality-driven processes, iterative refinement, or retry logic.

**Example**: Research until sufficient quality, iterative improvement

![Loop Steps](assets/loop_steps.png)

```python
from agno.workflow import Loop, Step, Workflow

def quality_check(outputs) -> bool:
    # Return True to break loop, False to continue
    return any(len(output.content) > 500 for output in outputs)

workflow = Workflow(
    name="Quality-Driven Research",
    steps=[
        Loop(
            name="Research Loop",
            steps=[Step(name="Deep Research", agent=researcher)],
            end_condition=quality_check,
            max_iterations=3
        ),
        Step(name="Final Analysis", agent=analyst),
    ]
)

workflow.print_response("Research the impact of renewable energy on global markets", markdown=True)
```

**See Examples**:
- [`loop_steps_workflow.py`](_03_workflows_loop_execution/sync/loop_steps_workflow.py)
- [`loop_steps_workflow_stream.py`](_03_workflows_loop_execution/sync/loop_steps_workflow_stream.py)

### 7. Condition-Based Branching

**When to use**: Complex decision trees, topic-specific workflows, dynamic routing.

**Example**: Content type detection, expertise routing

![Router Steps](assets/router_steps.png)

```python
from agno.workflow import Router, Step, Workflow

def route_by_topic(step_input) -> List[Step]:
    topic = step_input.input.lower()

    if "tech" in topic:
        return [Step(name="Tech Research", agent=tech_expert)]
    elif "business" in topic:
        return [Step(name="Business Research", agent=biz_expert)]
    else:
        return [Step(name="General Research", agent=generalist)]

workflow = Workflow(
    name="Expert Routing",
    steps=[
        Router(
            name="Topic Router",
            selector=route_by_topic,
            choices=[tech_step, business_step, general_step]
        ),
        Step(name="Synthesis", agent=synthesizer),
    ]
)

workflow.print_response("Latest developments in artificial intelligence and machine learning", markdown=True)
```

**See Examples**:
- [`router_steps_workflow.py`](_05_workflows_conditional_branching/sync/router_steps_workflow.py)
- [`router_steps_workflow_stream.py`](_05_workflows_conditional_branching/sync/router_steps_workflow_stream.py)

### 8. Steps: Grouping a list of steps

**When to use**: When you need to group multiple steps into logical sequences, create reusable workflows, or organize complex workflows with multiple branching paths.

Better Routing: Use with Router for clean branching logic

```python
from agno.workflow import Steps, Step, Workflow

# Create a reusable content creation sequence
article_creation_sequence = Steps(
    name="ArticleCreation",
    description="Complete article creation workflow from research to final edit",
    steps=[
        Step(name="research", agent=researcher),
        Step(name="writing", agent=writer),
        Step(name="editing", agent=editor),
    ],
)

# Use the sequence in a workflow
workflow = Workflow(
    name="Article Creation Workflow",
    steps=[article_creation_sequence]  # Single sequence
)

workflow.print_response("Write an article about renewable energy", markdown=True)
```

#### Steps with Router for Clean Branching
This is where Steps really shines - creating distinct sequences for different content types or workflows:

```python
from agno.workflow import Steps, Router, Step, Workflow

# Define two completely different workflows as Steps
image_sequence = Steps(
    name="image_generation",
    description="Complete image generation and analysis workflow",
    steps=[
        Step(name="generate_image", agent=image_generator),
        Step(name="describe_image", agent=image_describer),
    ],
)

video_sequence = Steps(
    name="video_generation",
    description="Complete video production and analysis workflow",
    steps=[
        Step(name="generate_video", agent=video_generator),
        Step(name="describe_video", agent=video_describer),
    ],
)

def media_sequence_selector(step_input) -> List[Step]:
    """Route to appropriate media generation pipeline"""
    if not step_input.input:
        return [image_sequence]
    message_lower = step_input.input.lower()

    if "video" in message_lower:
        return [video_sequence]
    elif "image" in message_lower:
        return [image_sequence]
    else:
        return [image_sequence]  # Default

# Clean workflow with clear branching
media_workflow = Workflow(
    name="AI Media Generation Workflow",
    description="Generate and analyze images or videos using AI agents",
    steps=[
        Router(
            name="Media Type Router",
            description="Routes to appropriate media generation pipeline",
            selector=media_sequence_selector,
            choices=[image_sequence, video_sequence],  # Clear choices
        )
    ],
)

# Usage examples
media_workflow.print_response("Create an image of a magical forest", markdown=True)
media_workflow.print_response("Create a cinematic video of city timelapse", markdown=True)
```

**See Examples**
- [`workflow_using_steps.py`](_01_basic_workflows/_01_sequence_of_steps/sync/workflow_using_steps.py)
- [`workflow_using_steps_nested.py`](_01_basic_workflows/_01_sequence_of_steps/sync/workflow_using_steps_nested.py)
- [`selector_for_image_video_generation_pipelines.py`](_05_workflows_conditional_branching/sync/selector_for_image_video_generation_pipelines.py)

### 9. Complex Combinations

**When to use**: Sophisticated workflows requiring multiple patterns.

**Example**: Conditions + Parallel + Loops + Custom Post-Processing Function + Routing

```python
from agno.workflow import Condition, Loop, Parallel, Router, Step, Workflow

def research_post_processor(step_input) -> StepOutput:
    """Post-process and consolidate research data from parallel conditions"""
    research_data = step_input.previous_step_content or ""

    try:
        # Analyze research quality and completeness
        word_count = len(research_data.split())
        has_tech_content = any(keyword in research_data.lower()
                              for keyword in ["technology", "ai", "software", "tech"])
        has_business_content = any(keyword in research_data.lower()
                                  for keyword in ["market", "business", "revenue", "strategy"])

        # Create enhanced research summary
        enhanced_summary = f"""
            ## Research Analysis Report

            **Data Quality:** {"✓ High-quality" if word_count > 200 else "⚠ Limited data"}

            **Content Coverage:**
            - Technical Analysis: {"✓ Completed" if has_tech_content else "✗ Not available"}
            - Business Analysis: {"✓ Completed" if has_business_content else "✗ Not available"}

            **Research Findings:**
            {research_data}
        """.strip()

        return StepOutput(
            content=enhanced_summary,
            success=True,
        )

    except Exception as e:
        return StepOutput(
            content=f"Research post-processing failed: {str(e)}",
            success=False,
            error=str(e)
        )

# Complex workflow combining multiple patterns
workflow = Workflow(
    name="Advanced Multi-Pattern Workflow",
    steps=[
        Parallel(
            Condition(
                name="Tech Check",
                evaluator=is_tech_topic,
                steps=[Step(name="Tech Research", agent=tech_researcher)]
            ),
            Condition(
                name="Business Check",
                evaluator=is_business_topic,
                steps=[
                    Loop(
                        name="Deep Business Research",
                        steps=[Step(name="Market Research", agent=market_researcher)],
                        end_condition=research_quality_check,
                        max_iterations=3
                    )
                ]
            ),
            name="Conditional Research Phase"
        ),
        Step(
            name="Research Post-Processing",
            executor=research_post_processor,
            description="Consolidate and analyze research findings with quality metrics"
        ),
        Router(
            name="Content Type Router",
            selector=content_type_selector,
            choices=[blog_post_step, social_media_step, report_step]
        ),
        Step(name="Final Review", agent=reviewer),
    ]
)

workflow.print_response("Create a comprehensive analysis of sustainable technology trends and their business impact for 2024", markdown=True)
```

**See Examples**:
- [`condition_and_parallel_steps_stream.py`](_02_workflows_conditional_execution/sync/condition_and_parallel_steps_stream.py)
- [`loop_with_parallel_steps_stream.py`](_03_workflows_loop_execution/sync/loop_with_parallel_steps_stream.py)
- [`router_with_loop_steps.py`](_05_workflows_conditional_branching/sync/router_with_loop_steps.py)

## Advanced Features

### Early Stopping

Workflows can be terminated early when certain conditions are met, preventing unnecessary processing and ensuring safety gates work properly. Any step can trigger early termination by returning `StepOutput(stop=True)`.

![Early Stop Workflows](assets/early_stop.png)

```python
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput

def security_gate(step_input: StepInput) -> StepOutput:
    """Security gate that stops deployment if vulnerabilities found"""
    security_result = step_input.previous_step_content or ""

    if "VULNERABLE" in security_result.upper():
        return StepOutput(
            content="🚨 SECURITY ALERT: Critical vulnerabilities detected. Deployment blocked.",
            stop=True  # Stop the entire workflow
        )
    else:
        return StepOutput(
            content="✅ Security check passed. Proceeding with deployment...",
            stop=False
        )

# Secure deployment pipeline
workflow = Workflow(
    name="Secure Deployment Pipeline",
    steps=[
        Step(name="Security Scan", agent=security_scanner),
        Step(name="Security Gate", executor=security_gate),  # May stop here
        Step(name="Deploy Code", agent=code_deployer),       # Only if secure
        Step(name="Setup Monitoring", agent=monitoring_agent), # Only if deployed
    ]
)

# Test with vulnerable code - workflow stops at security gate
workflow.print_response("Scan this code: exec(input('Enter command: '))")
```

**See Examples**:
- [`early_stop_workflow_with_agents.py`](_06_advanced_concepts/_02_early_stopping/early_stop_workflow_with_agents.py)
- [`early_stop_workflow_with_loop.py`](_06_advanced_concepts/_02_early_stopping/early_stop_workflow_with_loop.py)
- [`early_stop_workflow_with_router.py`](_06_advanced_concepts/_02_early_stopping/early_stop_workflow_with_router.py)

### Access Multiple Previous Steps Output

Advanced workflows often need to access data from multiple previous steps, not just the immediate previous step. The `StepInput` object provides powerful methods to access any previous step's output by name or get all previous content.

```python
def create_comprehensive_report(step_input: StepInput) -> StepOutput:
    """
    Custom function that creates a report using data from multiple previous steps.
    This function has access to ALL previous step outputs and the original workflow message.
    """

    # Access original workflow input
    original_topic = step_input.input or ""

    # Access specific step outputs by name
    hackernews_data = step_input.get_step_content("research_hackernews") or ""
    web_data = step_input.get_step_content("research_web") or ""

    # Or access ALL previous content
    all_research = step_input.get_all_previous_content()

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

    return StepOutput(
        step_name="comprehensive_report",
        content=report.strip(),
        success=True
    )

# Use in workflow
workflow = Workflow(
    name="Enhanced Research Workflow",
    steps=[
        Step(name="research_hackernews", agent=hackernews_agent),
        Step(name="research_web", agent=web_agent),
        Step(name="comprehensive_report", executor=create_comprehensive_report),  # Accesses both previous steps
        Step(name="final_reasoning", agent=reasoning_agent),
    ],
)
```

> **Key Methods:**
> - `step_input.get_step_content("step_name")` - Get content from specific step by name
> - `step_input.get_all_previous_content()` - Get all previous step content combined
> - `step_input.input` - Access the original workflow input message
> - `step_input.previous_step_content` - Get content from immediate previous step

### Event Storage and Filtering

Workflows can automatically store all events for later analysis, debugging, or audit purposes. You can also filter out specific event types to reduce noise and storage overhead. You can access these events on the `WorkflowRunOutput` and in the `runs` column in your `Workflow's Session DB`

**Key Features:**

- **`store_events=True`**: Automatically stores all workflow events in the database
- **`events_to_skip=[]`**: Filter out specific event types to reduce storage and noise
- **Persistent Storage**: Events are stored in your configured storage backend (SQLite, PostgreSQL, etc.)
- **Post-Execution Access**: Access all stored events via `run_response.events`

**Available Events to Skip:**
```python
from agno.run.workflow import WorkflowRunEvent

# Common events you might want to skip
events_to_skip = [
    WorkflowRunEvent.workflow_started,
    WorkflowRunEvent.workflow_completed,
    WorkflowRunEvent.step_started,
    WorkflowRunEvent.step_completed,
    WorkflowRunEvent.parallel_execution_started,
    WorkflowRunEvent.parallel_execution_completed,
    WorkflowRunEvent.condition_execution_started,
    WorkflowRunEvent.condition_execution_completed,
    WorkflowRunEvent.loop_execution_started,
    WorkflowRunEvent.loop_execution_completed,
    WorkflowRunEvent.router_execution_started,
    WorkflowRunEvent.router_execution_completed,
]
```

**When to use:**
- **Debugging**: Store all events to analyze workflow execution flow
- **Audit Trails**: Keep records of all workflow activities for compliance
- **Performance Analysis**: Analyze timing and execution patterns
- **Error Investigation**: Review event sequences leading to failures
- **Noise Reduction**: Skip verbose events like `step_started` to focus on results

**Example Use Cases:**
```python
# store everything
debug_workflow = Workflow(
    name="Debug Workflow",
    store_events=True,
    steps=[...]
)

# store only important events
production_workflow = Workflow(
    name="Production Workflow",
    store_events=True,
    events_to_skip=[
        WorkflowRunEvent.step_started,
        WorkflowRunEvent.parallel_execution_started,
        # keep step_completed and workflow_completed
    ],
    steps=[...]
)

# No event storage
fast_workflow = Workflow(
    name="Fast Workflow",
    store_events=False,
    steps=[...]
)
```

**See Examples**:
- [`store_events_and_events_to_skip_in_a_workflow.py`](_06_advanced_concepts/_07_other/store_events_and_events_to_skip_in_a_workflow.py)

### Additional Data

**When to use**: When you need to pass metadata, configuration, or contextual information to specific steps without it being part of the main workflow message flow.
- Separation of Concerns: Keep workflow logic separate from metadata
- Step-Specific Context: Access additional information in custom functions
- Clean Message Flow: Main message stays focused on content
- Flexible Configuration: Pass user info, priorities, settings, etc.

Access Pattern: `step_input.additional_data` provides dictionary access to all additional data

```python
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput

def custom_content_planning_function(step_input: StepInput) -> StepOutput:
    """Custom function that uses additional_data for enhanced context"""

    # Access the main workflow message
    message = step_input.input
    previous_content = step_input.previous_step_content

    # Access additional_data that was passed with the workflow
    additional_data = step_input.additional_data or {}
    user_email = additional_data.get("user_email", "No email provided")
    priority = additional_data.get("priority", "normal")
    client_type = additional_data.get("client_type", "standard")

    # Create enhanced planning prompt with context
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {message}
        Research Results: {previous_content[:500] if previous_content else "No research results"}

        Additional Context:
        - Client Type: {client_type}
        - Priority Level: {priority}
        - Contact Email: {user_email}

        {"🚨 HIGH PRIORITY - Expedited delivery required" if priority == "high" else "📝 Standard delivery timeline"}

        Please create a detailed, actionable content plan.
    """

    response = content_planner.run(planning_prompt)

    enhanced_content = f"""
        ## Strategic Content Plan

        **Planning Topic:** {message}
        **Client Details:** {client_type} | {priority.upper()} priority | {user_email}

        **Content Strategy:**
        {response.content}
    """

    return StepOutput(content=enhanced_content, response=response)

# Define workflow with steps
workflow = Workflow(
    name="Content Creation Workflow",
    steps=[
        Step(name="Research Step", team=research_team),
        Step(name="Content Planning Step", executor=custom_content_planning_function),
    ]
)

# Run workflow with additional_data
workflow.print_response(
    input="AI trends in 2024",
    additional_data={
        "user_email": "kaustubh@agno.com",
        "priority": "high",
        "client_type": "enterprise",
        "budget": "$50000",
        "deadline": "2024-12-15"
    },
    markdown=True,
    stream=True
)
```

**See**: [`step_with_function_additional_data.py`](_01_basic_workflows/_02_step_with_function/sync/step_with_function_additional_data.py)

### Streaming Support

This adds support for having streaming event-based information for your workflows:

```python
from agno.workflow import Workflow
from agno.run.workflow import (
    WorkflowStartedEvent,
    StepStartedEvent,
    StepCompletedEvent,
    WorkflowCompletedEvent
)

# Enable streaming for any workflow pattern
workflow = Workflow(
    name="Streaming Pipeline",
    steps=[research_step, analysis_step, writing_step]
)

# Stream with proper event handling
for event in workflow.run(input="AI trends", stream=True, stream_events=True):
    if isinstance(event, WorkflowStartedEvent):
        print(f"🚀 Workflow Started: {event.workflow_name}")
        print(f"   Run ID: {event.run_id}")

    elif isinstance(event, StepStartedEvent):
        print(f"📍 Step Started: {event.step_name}")
        print(f"   Step Index: {event.step_index}")

    elif isinstance(event, StepCompletedEvent):
        print(f"✅ Step Completed: {event.step_name}")
        # Show content preview instead of full content
        if hasattr(event, 'content') and event.content:
            preview = str(event.content)[:100] + "..." if len(str(event.content)) > 100 else str(event.content)
            print(f"   Preview: {preview}")

    elif isinstance(event, WorkflowCompletedEvent):
        print(f"🎉 Workflow Completed: {event.workflow_name}")
        print(f"   Total Steps: {len(event.step_results)}")
        # Show final output preview
        if hasattr(event, 'content') and event.content:
            preview = str(event.content)[:150] + "..." if len(str(event.content)) > 150 else str(event.content)
            print(f"   Final Output: {preview}")
```

**See**: Any `*_stream.py` file for streaming examples.

### Session State Management

Share data across workflow steps:

```python
from agno.workflow import Workflow
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat

# Access state in agent tools
def add_to_shared_data(session_state, data: str) -> str:
    session_state["collected_data"] = data
    return f"Added: {data}"

shopping_assistant = Agent(
    name="Shopping Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_to_shared_data],
    instructions=[
        "You are a helpful shopping assistant.",
        "You can help users manage their shopping list by adding, removing, and listing items.",
        "Always use the provided tools to interact with the shopping list.",
        "Be friendly and helpful in your responses.",
    ],
)

workflow = Workflow(
    name="Stateful Workflow",
    session_state={},  # Initialize shared state
    steps=[data_collector_step, data_processor_step, data_finalizer_step]
)

workflow.print_response("Add apples and oranges to my shopping list")
```

**See**:
- [`shared_session_state_with_agent.py`](06_advanced_concepts/04_shared_session_state/shared_session_state_with_agent.py)
- [`shared_session_state_with_team.py`](06_advanced_concepts/04_shared_session_state/shared_session_state_with_team.py)

### Background Execution

Execute workflows asynchronously in the background and monitor their progress using polling or real-time updates:

```python
import asyncio
from agno.workflow import Workflow

# Start workflow execution in background
async def main():
    bg_response = await workflow.arun(
        input="AI trends in 2024",
        background=True
    )
    print(f"Run ID: {bg_response.run_id}")

    # Poll for completion
    while True:
        result = workflow.get_run(bg_response.run_id)

        if result and result.has_completed():
            break

        await asyncio.sleep(5)  # Poll every 5 seconds

    print("Workflow completed!")
```

**See**:
- [`background_execution_poll.py`](/cookbook/workflows/_06_advanced_concepts/_05_background_execution/background_execution_poll.py)
- [`background_execution_using_websocket`](/cookbook/workflows/_06_advanced_concepts/_05_background_execution/background_execution_using_websocket)

### Structured Inputs

Use Pydantic models for type-safe inputs:

```python
from pydantic import BaseModel, Field

class ResearchRequest(BaseModel):
    topic: str = Field(description="Research topic")
    depth: int = Field(description="Research depth (1-10)")
    sources: List[str] = Field(description="Preferred sources")

workflow.print_response(
    input=ResearchRequest(
        topic="AI trends 2024",
        depth=8,
        sources=["academic", "industry"]
    )
)
```

**See**: [`pydantic_model_as_input.py`](06_advanced_concepts/01_structured_io_at_each_level/pydantic_model_as_input.py)

## Best Practices

### When to Use Each Pattern

| Pattern | Best For | Avoid When |
|---------|----------|------------|
| **Sequential** | Linear processes, dependencies | Independent tasks |
| **Parallel** | Independent tasks, speed optimization | Sequential dependencies |
| **Conditional** | Topic-specific logic, branching | Simple linear flows |
| **Loop** | Quality assurance, retry logic | Known finite processes |
| **Router** | Complex decision trees | Simple if/else logic |
| **Mixed** | Maximum flexibility | Simple workflows |

## Migration from Workflows 1.0

### Key Differences

| Workflows 1.0 | Workflows 2.0 | Migration Path |
|---------------|---------------|----------------|
| Linear only | Multiple patterns | Add Parallel/Condition as needed |
| Agent-focused | Mixed components | Convert functions to Steps |
| Limited branching | Smart routing | Replace if/else with Router |
| Manual loops | Built-in Loop | Use Loop component |

### Migration Steps

1. **Assess current workflow**: Identify parallel opportunities
2. **Add conditions**: Convert if/else logic to Condition components
3. **Extract functions**: Move custom logic to function-based steps
4. **Enable streaming**: For event-based information
5. **Add state management**: Use `session_state` for data sharing

For more examples and advanced patterns, explore the following directories-
- [`01_basic_workflows/`](01_basic_workflows)
- [`02_workflows_conditional_execution/`](02_workflows_conditional_execution)
- [`03_workflows_loop_execution/`](03_workflows_loop_execution)
- [`04_workflows_parallel_execution/`](04_workflows_parallel_execution)
- [`05_workflows_conditional_branching/`](05_workflows_conditional_branching)
- [`06_advanced_concepts/`](06_advanced_concepts)

Each file demonstrates a specific pattern with detailed comments and real-world use cases.
