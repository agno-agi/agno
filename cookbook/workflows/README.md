# Agno Workflows 2.0 - Developer Guide

Welcome to **Agno Workflows 2.0** - the next generation of intelligent, flexible workflow orchestration. This guide covers all workflow patterns, from simple linear sequences to complex conditional logic with parallel execution.

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [Workflow Patterns](#workflow-patterns)
  - [1. Sequential Workflows](#1-sequential-workflows)
  - [2. Parallel Execution](#2-parallel-execution)
  - [3. Conditional Workflows](#3-conditional-workflows)
  - [4. Loop/Iteration Workflows](#4-loopiteration-workflows)
  - [5. Condition-Based Branching](#5-Condition-based-branching)
  - [6. Function-Based Steps](#6-function-based-steps)
  - [7. Mixed Execution Types](#7-mixed-execution-types)
  - [8. Complex Combinations](#8-complex-combinations)
- [Advanced Features](#advanced-features)
- [Best Practices](#best-practices)
- [Migration from Workflows 1.0](#migration-from-workflows-10)

## Overview

Agno Workflows 2.0 provides a powerful, declarative way to orchestrate multi-step AI processes. Unlike traditional linear workflows, you can now create sophisticated branching logic, parallel execution, and dynamic routing based on content analysis.

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

## Getting Started

1. **Start Simple**: Begin with sequential workflows
2. **Add Parallelism**: Identify independent tasks
3. **Introduce Conditions**: Add content-aware branching
4. **Enable Streaming**: Have event-based information
5. **Scale Complexity**: Combine patterns as needed

## Workflow Patterns

### 1. Sequential Workflows

**When to use**: Linear processes where each step depends on the previous one.

**Example**: Research → Analysis → Content Creation

```python
from agno.workflow.v2 import Step, Workflow

# Simple sequential workflow - just use agents directly
workflow = Workflow(
    name="Content Creation Pipeline",
    steps=[
        researcher,  # Agent
        analyst,     # Agent 
        writer,      # Agent
    ]
)

# Run the workflow
workflow.print_response(
    "AI trends in 2024",
    markdown=True,
)
```

**You can name your steps** for better logging and future support on the Agno platform:

```python
from agno.workflow.v2 import Step, Workflow

# Named steps for better tracking
workflow = Workflow(
    name="Content Creation Pipeline",
    steps=[
        Step(name="Research Phase", agent=researcher),
        Step(name="Analysis Phase", agent=analyst), 
        Step(name="Writing Phase", agent=writer),
    ]
)

workflow.print_response(
    "AI trends in 2024",
    markdown=True,
)
```

**See**: [`sequence_of_steps.py`](sync/sequence_of_steps.py)

### 2. Parallel Execution

**When to use**: Independent tasks that can run simultaneously to save time.

**Example**: Multiple research sources, parallel content creation

![Parallel Steps](/cookbook/workflows/assets/parallel_steps.png)

```python
from agno.workflow.v2 import Parallel, Step, Workflow

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

**See**: [`parallel_steps_workflow.py`](sync/parallel_steps_workflow.py)

### 3. Conditional Steps

**When to use**: Conditional step execution based on business logic.

**Example**: Topic-specific research strategies, content type routing

![Condition Steps](/cookbook/workflows/assets/condition_steps.png)

```python
from agno.workflow.v2 import Condition, Step, Workflow

def is_tech_topic(step_input) -> bool:
    topic = step_input.message.lower()
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

**See**: [`condition_with_list_of_steps.py`](sync/condition_with_list_of_steps.py)

### 4. Loop/Iteration Workflows

**When to use**: Quality-driven processes, iterative refinement, or retry logic.

**Example**: Research until sufficient quality, iterative improvement

![Loop Steps](/cookbook/workflows/assets/loop_steps.png)

```python
from agno.workflow.v2 import Loop, Step, Workflow

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

**See**: [`loop_steps_workflow.py`](sync/loop_steps_workflow.py)

### 5. Condition-Based Branching

**When to use**: Complex decision trees, topic-specific workflows, dynamic routing.

**Example**: Content type detection, expertise routing

![Router Steps](/cookbook/workflows/assets/router_steps.png)

```python
from agno.workflow.v2 import Router, Step, Workflow

def route_by_topic(step_input) -> List[Step]:
    topic = step_input.message.lower()
    
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

**See**: [`router_steps_workflow.py`](sync/router_steps_workflow.py)

### 6. Function-Based Steps

**When to use**: Custom business logic, API integrations, data transformations.

**Example**: Custom processing with agent integration

![Custom Function Steps](/cookbook/workflows/assets/custom_function_steps.png)

```python
from agno.workflow.v2 import Step, Workflow

def custom_processor(step_input) -> StepOutput:
    # Custom logic with agent interaction
    processed_data = some_custom_logic(step_input.message)
    agent_response = content_agent.run(processed_data)
    
    return StepOutput(
        content=f"Enhanced: {agent_response.content}",
        response=agent_response
    )

workflow = Workflow(
    name="Custom Processing Pipeline",
    steps=[
        Step(name="Research", agent=researcher),
        Step(name="Custom Processing", executor=custom_processor),
        Step(name="Final Review", agent=reviewer),
    ]
)

workflow.print_response("Create a technical analysis of blockchain scalability solutions", markdown=True)
```

**See**: [`step_with_function.py`](sync/step_with_function.py)

### 7. Mixed Execution Types

**When to use**: Combining different execution types (agents, teams, functions) in one workflow.

**Example**: Function → Team → Agent → Function

```python
from agno.workflow.v2 import Step, Workflow

def data_preprocessor(step_input):
    # Custom preprocessing logic
    return StepOutput(content=f"Processed: {step_input.message}")

workflow = Workflow(
    name="Mixed Execution Pipeline",
    steps=[
        data_preprocessor,  # Function
        research_team,      # Team
        Step(name="Analysis", agent=analyst),  # Agent
        Step(name="Custom Logic", executor=custom_function),  # Function in Step
    ]
)

workflow.print_response("Analyze the competitive landscape for fintech startups", markdown=True)
```

**See**: [`sequence_of_functions_and_agents.py`](sync/sequence_of_functions_and_agents.py)

### 8. Complex Combinations

**When to use**: Sophisticated workflows requiring multiple patterns.

**Example**: Conditions + Parallel + Loops + Custom Post-Processing Function + Routing

```python
from agno.workflow.v2 import Condition, Loop, Parallel, Router, Step, Workflow

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

**See**: [`condition_and_parallel_steps.py`](sync/condition_and_parallel_steps.py), [`router_with_loop_steps.py`](sync/router_with_loop_steps.py)

## Advanced Features

### Streaming Support

This adds support for having streaming event-based information for your workflows:

```python
from agno.workflow.v2 import Workflow
from agno.run.v2.workflow import (
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
for event in workflow.run(message="AI trends", stream=True, stream_intermediate_steps=True):
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
        print(f"   Total Steps: {len(event.step_responses)}")
        # Show final output preview
        if hasattr(event, 'content') and event.content:
            preview = str(event.content)[:150] + "..." if len(str(event.content)) > 150 else str(event.content)
            print(f"   Final Output: {preview}")
```

**See**: Any `*_stream.py` file for streaming examples.

### Session State Management

Share data across workflow steps:

```python
from agno.workflow.v2 import Workflow
from agno.agent.agent import Agent

# Access state in agent tools
def add_to_shared_data(agent: Agent, data: str) -> str:
    agent.workflow_session_state["collected_data"] = data
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
    workflow_session_state={},  # Initialize shared state
    steps=[data_collector_step, data_processor_step, data_finalizer_step]
)

workflow.print_response("Add apples and oranges to my shopping list")
```

**See**: [`shared_session_state_with_agent.py`](sync/shared_session_state_with_agent.py)

### Structured Inputs

Use Pydantic models for type-safe inputs:

```python
from pydantic import BaseModel, Field

class ResearchRequest(BaseModel):
    topic: str = Field(description="Research topic")
    depth: int = Field(description="Research depth (1-10)")
    sources: List[str] = Field(description="Preferred sources")

workflow.print_response(
    message=ResearchRequest(
        topic="AI trends 2024",
        depth=8,
        sources=["academic", "industry"]
    )
)
```

**See**: [`pydantic_model_as_input.py`](sync/pydantic_model_as_input.py)

### Custom Workflow Execution

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

**See**: [`function_instead_of_steps.py`](sync/function_instead_of_steps.py)

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
5. **Add state management**: Use `workflow_session_state` for data sharing

## Examples by Use Case

### Content Creation Pipeline
- **Pattern**: Sequential
- **See**: [`sequence_of_steps.py`](sync/sequence_of_steps.py)

### Multi-Source Research
- **Pattern**: Parallel + Conditional
- **See**: [`condition_and_parallel_steps.py`](sync/condition_and_parallel_steps.py)

### Quality-Driven Processing
- **Pattern**: Loop + Conditional
- **See**: [`loop_steps_workflow.py`](sync/loop_steps_workflow.py)

### Dynamic Expert Routing
- **Pattern**: Router + Mixed components
- **See**: [`router_steps_workflow.py`](sync/router_steps_workflow.py)

### Custom Business Logic
- **Pattern**: Function-based + Mixed
- **See**: [`step_with_function.py`](sync/step_with_function.py)

### Stateful Multi-Step Process
- **Pattern**: Sequential + State management
- **See**: [`shared_session_state_with_agent.py`](sync/shared_session_state_with_agent.py)

For more examples and advanced patterns, explore the [`cookbook/workflows/sync/`](sync/) and [`cookbook/workflows/async/`](async/) directory. Each file demonstrates a specific pattern with detailed comments and real-world use cases.
