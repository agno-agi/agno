"""
Step History
============

Demonstrates workflow-level and step-level history controls for conversation-aware content workflows.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents (Meal Planning Workflow)
# ---------------------------------------------------------------------------
meal_suggester = Agent(
    name="Meal Suggester",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a friendly meal planning assistant who suggests meal categories and cuisines.",
        "Consider the time of day, day of the week, and any context from the conversation.",
        "Keep suggestions broad (Italian, Asian, healthy, comfort food, quick meals, etc.)",
        "Ask follow-up questions to understand preferences better.",
    ],
)

recipe_specialist = Agent(
    name="Recipe Specialist",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a recipe expert who provides specific, detailed recipe recommendations.",
        "Pay close attention to the full conversation to understand user preferences and restrictions.",
        "If the user mentioned avoiding certain foods or wanting healthier options, respect that.",
        "Provide practical, easy-to-follow recipe suggestions with ingredients and basic steps.",
        "Reference the conversation naturally (e.g., 'Since you mentioned wanting something healthier...').",
    ],
)


# ---------------------------------------------------------------------------
# Define Function (Meal Preference Analysis)
# ---------------------------------------------------------------------------
def analyze_food_preferences(step_input: StepInput) -> StepOutput:
    current_request = step_input.input
    conversation_context = step_input.previous_step_content or ""

    preferences = {
        "dietary_restrictions": [],
        "cuisine_preferences": [],
        "avoid_list": [],
        "cooking_style": "any",
    }

    full_context = f"{conversation_context} {current_request}".lower()

    if any(word in full_context for word in ["healthy", "healthier", "light", "fresh"]):
        preferences["dietary_restrictions"].append("healthy")
    if any(word in full_context for word in ["vegetarian", "veggie", "no meat"]):
        preferences["dietary_restrictions"].append("vegetarian")
    if any(word in full_context for word in ["quick", "fast", "easy", "simple"]):
        preferences["cooking_style"] = "quick"
    if any(word in full_context for word in ["comfort", "hearty", "filling"]):
        preferences["cooking_style"] = "comfort"

    if "italian" in full_context and (
        "had" in full_context or "yesterday" in full_context
    ):
        preferences["avoid_list"].append("Italian")
    if "chinese" in full_context and (
        "had" in full_context or "recently" in full_context
    ):
        preferences["avoid_list"].append("Chinese")

    if "love asian" in full_context or "like asian" in full_context:
        preferences["cuisine_preferences"].append("Asian")
    if "mediterranean" in full_context:
        preferences["cuisine_preferences"].append("Mediterranean")

    guidance = []
    if preferences["dietary_restrictions"]:
        guidance.append(
            f"Focus on {', '.join(preferences['dietary_restrictions'])} options"
        )
    if preferences["avoid_list"]:
        guidance.append(
            f"Avoid {', '.join(preferences['avoid_list'])} cuisine since user had it recently"
        )
    if preferences["cuisine_preferences"]:
        guidance.append(
            f"Consider {', '.join(preferences['cuisine_preferences'])} options"
        )
    if preferences["cooking_style"] != "any":
        guidance.append(f"Prefer {preferences['cooking_style']} cooking style")

    analysis_result = f"""
        PREFERENCE ANALYSIS:
        Current Request: {current_request}

        Detected Preferences:
        {chr(10).join(f"- {g}" for g in guidance) if guidance else "- No specific preferences detected"}

        RECIPE AGENT GUIDANCE:
        Based on the conversation history, please provide recipe recommendations that align with these preferences.
        Reference the conversation naturally and explain why these recipes fit their needs.
    """.strip()

    return StepOutput(content=analysis_result)


# ---------------------------------------------------------------------------
# Define Steps (Meal Planning Workflow)
# ---------------------------------------------------------------------------
suggestion_step = Step(name="Meal Suggestion", agent=meal_suggester)
preference_analysis_step = Step(
    name="Preference Analysis", executor=analyze_food_preferences
)
recipe_step = Step(name="Recipe Recommendations", agent=recipe_specialist)

# ---------------------------------------------------------------------------
# Create Workflow (Workflow-Level History)
# ---------------------------------------------------------------------------
meal_workflow = Workflow(
    name="Conversational Meal Planner",
    description="Smart meal planning with conversation awareness and preference learning",
    db=SqliteDb(session_table="workflow_session", db_file="tmp/meal_workflow.db"),
    steps=[suggestion_step, preference_analysis_step, recipe_step],
    add_workflow_history_to_steps=True,
)

# ---------------------------------------------------------------------------
# Create Agents (Content Workflow)
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="Research Specialist",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a research specialist who gathers information on topics.",
        "Conduct thorough research and provide key facts, trends, and insights.",
        "Focus on current, accurate information from reliable sources.",
        "Organize your findings in a clear, structured format.",
        "Provide citations and context for your research.",
    ],
)

content_creator = Agent(
    name="Content Creator",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are an expert content creator who writes engaging content.",
        "Use the research provided and CREATE UNIQUE content that stands out.",
        "IMPORTANT: Review workflow history to understand:",
        "- What content topics have been covered before",
        "- What writing styles and formats were used previously",
        "- User preferences and content patterns",
        "- Avoid repeating similar content or approaches",
        "Build on previous themes while keeping content fresh and original.",
        "Reference the conversation history to maintain consistency in tone and style.",
        "Create compelling headlines, engaging intros, and valuable content.",
    ],
)

publisher_agent = Agent(
    name="Content Publisher",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a content publishing specialist.",
        "Review the created content and prepare it for publication.",
        "Add appropriate hashtags, formatting, and publishing recommendations.",
        "Suggest optimal posting times and distribution channels.",
        "Ensure content meets platform requirements and best practices.",
    ],
)

# ---------------------------------------------------------------------------
# Create Workflow (Step-Level History)
# ---------------------------------------------------------------------------
content_workflow = Workflow(
    name="Smart Content Creation Pipeline",
    description="Research -> Content Creation (with history awareness) -> Publishing",
    db=SqliteDb(db_file="tmp/content_workflow.db"),
    steps=[
        Step(name="Research Phase", agent=research_agent, add_workflow_history=True),
        Step(name="Content Creation", agent=content_creator, add_workflow_history=True),
        Step(name="Content Publishing", agent=publisher_agent),
    ],
)


# ---------------------------------------------------------------------------
# Run Workflows
# ---------------------------------------------------------------------------
def demonstrate_conversational_meal_planning() -> None:
    session_id = "meal_planning_demo"

    print("Conversational Meal Planning Demo")
    print("=" * 60)

    print("\nUser: What should I cook for dinner tonight?")
    meal_workflow.print_response(
        input="What should I cook for dinner tonight?",
        session_id=session_id,
        markdown=True,
    )

    print("\nUser: I had Italian yesterday, and I'm trying to eat healthier these days")
    meal_workflow.print_response(
        input="I had Italian yesterday, and I'm trying to eat healthier these days",
        session_id=session_id,
        markdown=True,
    )

    print("\nUser: Actually, do you have something with fish? I love Asian flavors too")
    meal_workflow.print_response(
        input="Actually, do you have something with fish? I love Asian flavors too",
        session_id=session_id,
        markdown=True,
    )


def demo_content_history_cli() -> None:
    print("Content Creation Demo - Step-Level History Control")
    print("Only selected steps see previous workflow history")
    print("")
    print("Try these content requests:")
    print("- 'Create a LinkedIn post about AI trends in 2024'")
    print("- 'Write a Twitter thread about productivity tips'")
    print("- 'Create a blog intro about remote work benefits'")
    print("")
    print("Type 'exit' to quit")
    print("-" * 70)

    content_workflow.cli_app(
        session_id="content_demo",
        user="Content Requester",
        emoji="",
        stream=True,
    )


if __name__ == "__main__":
    demonstrate_conversational_meal_planning()
    demo_content_history_cli()
