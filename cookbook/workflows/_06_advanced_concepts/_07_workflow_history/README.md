# Workflow History & Continuous Execution

This guide demonstrates how to build conversational workflows that maintain context across multiple executions using Agno's workflow history feature.

## What is Workflow History?

Workflow history enables your workflows to remember and reference previous conversations, making them feel more natural and intelligent. Instead of treating each execution as isolated, workflows can:

- **Build on previous interactions** - Reference what users said before
- **Avoid repetitive questions** - Don't ask for information already provided
- **Maintain context continuity** - Create truly conversational experiences
- **Learn from patterns** - Analyze historical data to make better decisions

---

With this enabled the workflow history gets sent to the agent/team of the step in the following string format-
```bash
<workflow_history_context>
[run-1]
input: ...
response: ...

[run-2]
input: ...
response: ...
</workflow_history_context>
```

Along with this in case of custom function step you can access this history in the following ways-
1. As a formatted context string as shown above
2. In a structured format as well for more control
```bash
[
    (<workflow input from run 1>)(<workflow output from run 1>),
    (<workflow input from run 2>)(<workflow output from run 2>),
]
```

Example-
```python
def my_smart_function(step_input: StepInput) -> StepOutput:
    # Option 1: Structured data for analysis
    history_tuples = step_input.get_workflow_history(num_runs=3)
    for user_input, workflow_output in history_tuples:
        # Process each conversation turn

    # Option 2: Formatted context for agents  
    context_string = step_input.get_workflow_history_context(num_runs=3)

    return StepOutput(content="Analysis complete")
```

---

## Control Levels

### Workflow-Level History
Add workflow history to **all steps** in the workflow:

```python
workflow = Workflow(
    steps=[research_step, analysis_step, writing_step],
    add_workflow_history_to_steps=True  # All steps get history
)
```

### Step-Level History
Add workflow history to **specific steps** only:

```python
Step(
    name="Content Creator", 
    agent=content_agent,
    add_workflow_history=True  # Only this step gets history
)
```

### Precedence Logic

**Step-level settings always take precedence over workflow-level settings**:

```python
workflow = Workflow(
    steps=[
        Step("Research", agent=research_agent),                              # None → inherits workflow setting
        Step("Analysis", agent=analysis_agent, add_workflow_history=False),  # False → overrides workflow  
        Step("Writing", agent=writing_agent, add_workflow_history=True),     # True → overrides workflow
    ],
    add_workflow_history_to_steps=True  # Default for all steps
)
```

### History Length Control

**By default, ALL available history is included** (no limit). It is recommended to use a fixed history run limit to avoid bloating the LLM context window.

You can control this at both levels:

```python
# Workflow-level: limit history for all steps
workflow = Workflow(
    add_workflow_history_to_steps=True,
    num_history_runs=5  # Only last 5 runs
)

# Step-level: override for specific steps
Step("Analysis", agent=analysis_agent, 
     add_workflow_history=True,
     num_history_runs=3)  # Only last 3 runs for this step
```

## Where to start?

### 1. Single-Step Conversational Workflow
**File**: [`01_single_step_continuous_execution_workflow.py`](./01_single_step_continuous_execution_workflow.py)

Learn the basics with a simple AI tutor that remembers your conversation:

```python
# Simple single-step workflow with history
workflow = Workflow(
    steps=[Step(name="AI Tutoring", agent=tutor_agent)],
    add_workflow_history_to_steps=True
)
```

**Try it**: 
- Ask about calculus, then follow up with related questions
- Notice how the tutor references your previous discussions
- See how it avoids repeating information

---

### 2. Multi-Step with Smart Analysis  
**File**: [`02_workflow_with_history_enabled_for_steps.py`](./02_workflow_with_history_enabled_for_steps.py)

A meal planning workflow that learns your preferences through conversation:

```python
# Multi-step workflow with preference analysis
steps = [
    Step("Meal Suggestion", agent=meal_suggester),
    Step("Preference Analysis", executor=analyze_preferences),  # Custom function for analyzing outputs
    Step("Recipe Recommendations", agent=recipe_specialist)
]
```

**Key Features**:
- Custom function analyzes conversation patterns
- Agents adapt based on learned preferences  
- Natural conversation flow across multiple steps

---

### 3. Step-Level Control
**File**: [`03_enable_history_for_step.py`](./03_enable_history_for_step.py)

Learn when to enable history for specific steps only:

```python
# Only content creator needs history, not research or publishing
steps = [
    Step("Research", agent=research_agent),                    # No history
    Step("Content Creation", agent=content_agent, 
         add_workflow_history=True),                          # Has history  
    Step("Publishing", agent=publisher_agent)                 # No history
]
```

**Why Step-Level Control?**
- **Performance**: Only steps that benefit get history
- **Focus**: Reduces noise for steps that don't need context
- **Flexibility**: Mix history-aware and stateless steps

**Try it**:
- Ask it to create a Twitter thread about productivity tips
- After it responds, ask it to "Make it specifically about Software Engineering"
- Notice how the content creator references previous content

---

### 4. Custom Functions with History Access
**File**: [`04_get_history_in_function.py`](./04_get_history_in_function.py)

Show how custom Python functions can access and analyze workflow history:

```python
def analyze_content_strategy(step_input: StepInput) -> StepOutput:
    # Get structured history data
    history_data = step_input.get_workflow_history(num_runs=5)
    
    # Get formatted context string  
    history_context = step_input.get_workflow_history_context(num_runs=3)
    
    # Analyze patterns, detect overlaps, make recommendations
    # ... custom analysis logic ...
```

**Powerful Features**:
- **Dual access**: Get structured data OR formatted context
- **Pattern analysis**: Detect topic overlaps and content gaps
- **Strategic recommendations**: Guide subsequent agents
- **Real business value**: Prevent duplicate content, ensure progression

**Try it**:
- Ask it to create content about AI in healthcare
- After it responds, ask it to "Make it family focused"

---

### 5. Interactive CLI Demos
**File**: [`05_multi_purpose_cli.py`](./05_multi_purpose_cli.py)

Production-ready examples with full CLI interfaces:

- **Customer Support**: Multi-agent support pipeline with escalation
- **Medical Consultation**: Triage → Physician → Care Coordination  
- **Educational Tutoring**: Assessment → Teaching → Progress Planning

```bash
# Run specific demo
python 05_multi_purpose_cli.py support

# Interactive menu
python 05_multi_purpose_cli.py
```

### 6. Router with Shared History
**File**: [`06_intent_routing_with_history.py`](./06_intent_routing_with_history.py)

Demonstrates how different specialist agents can share the same conversation history, creating seamless handoffs:

```python
# All agents get the full conversation context
tech_step = Step("Technical Support", agent=tech_agent, add_workflow_history=True)
billing_step = Step("Billing Support", agent=billing_agent, add_workflow_history=True) 
general_step = Step("General Support", agent=general_agent, add_workflow_history=True)

# Simple router that focuses on shared history, not complex logic
Router(selector=simple_intent_router, choices=[tech_step, billing_step, general_step])
```

**Example Conversation Flow:**

```python
Customer: "I'm getting an error message"
→ Technical Support: "I'm sorry to hear about the error. Could you provide more details?"
Customer: "On login it says internal server error 500"
→ Technical Support: "Thank you for the details about the 500 error you mentioned earlier. Here's how to troubleshoot..."
Customer: "Thanks, also do I need to make sure my billing is done?"
→ Billing Support: "Certainly! Let me help with billing. I see you were having a 500 error issue..."
Customer: "Could less funds be the reason for the above error?"
→ Technical Support: "Generally, 500 errors aren't billing-related. However, given your earlier billing question..."
```

## API Reference

### Workflow Configuration
```python
Workflow(
    add_workflow_history_to_steps: bool = False,  # Enable for all steps
    num_history_runs: int = 3           # Number of previous runs to include
)
```

### Step Configuration  
```python
Step(
    add_workflow_history: bool = False,  # Enable for this step only
    num_history_runs: int = 3           # Override workflow default
)
```

### History Access in Custom Functions
```python
# Structured data access
step_input.get_workflow_history(num_runs: int = 3) -> List[Tuple[str, str]]

# Formatted context string
step_input.get_workflow_history_context(num_runs: int = 3) -> Optional[str]
```

--- 