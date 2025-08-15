from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.utils import WorkflowAction, WorkflowResponse


def create_agent(include_past_results=True):
    """Create an agent with or without past results"""
    PAST_RESULTS = """
You are a helpful assistant that can answer questions and help with tasks.

From previous results, you have the following information:

**Prologue:**
In a winter wonderland, where snow blanketed the ground and trees stood silently draped in white, a young girl named Lily wandered, full of curiosity and joy. Accompanying her was Max, her lively husky, whose vibrant energy filled the cold air with warmth. Together, they created countless adventures, reminding us of the bond between a child and her dog in the serene embrace of nature.

**Body:**
On one particularly whimsical day, while playing hide-and-seek among the snowy trees, Max's playful instincts led him to an unexpected discovery. As he rummaged through the underbrush, he unearthed an old, weathered box, obscured by layers of frost. Intrigued, Lily carefully dug it out, her excitement bubbling over as she brushed the snow from its surface. With a flick of her wrist, the box creaked open, revealing an assortment of letters and trinkets, glimpses of love and adventure long past. Each piece carried a story, and Lily felt a surge of inspiration to connect with her grandmother, hoping to learn the tales that intertwined their family's past. Max stood by her side, wagging his tail, embodying the spirit of companionship that was essential to this journey through memory.

**Epilogue:**
With the letters as their guide, Lily and her grandmother embarked on a path to rediscover forgotten stories, strengthening their family ties. Max, ever the loyal guardian, remained a joyful presence, creating new sparks of joy in this generational exchange. In the heart of the winter wonderland, amidst laughter and nostalgia, they wove a new tapestry of memories, showcasing how the echoes of the past can bring warmth to the present.

References: https://www.agno.com
"""

    INSTRUCTIONS = """
You are a multi-step workflow and you have the power to either:
    - Respond directly to the user's message
    - Ask for more information
    - Continue the workflow with a custom input

Note: If you continue the workflow, you must provide a workflow_input to the workflow. Make sure to only include required information in the custom input.

Information about workflow: The workflow generates a story based on a topic.
"""

    if include_past_results:
        instructions = f"{INSTRUCTIONS}\n{PAST_RESULTS}"
    else:
        instructions = INSTRUCTIONS

    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=instructions,
        response_model=WorkflowResponse,
    )


def test_workflow_scenario(
    question: str,
    expected_actions,
    include_past_results: bool = True,
    num_trials: int = 10,
) -> dict:
    """
    Test a specific workflow scenario

    Args:
        question: The question to ask
        expected_actions: What action(s) the agent should take (single action or list of actions)
        include_past_results: Whether to include past results in agent instructions
        num_trials: Number of times to test

    Returns:
        Dictionary with test results
    """
    # Handle both single action and list of actions
    if isinstance(expected_actions, WorkflowAction):
        expected_actions = [expected_actions]

    agent = create_agent(include_past_results)
    correct_responses = 0
    response_details = []

    print(f"\nTesting: '{question}'")
    print(f"Expected action(s): {[action.value for action in expected_actions]}")
    print(f"Past results included: {include_past_results}")
    print("-" * 50)

    for i in range(num_trials):
        try:
            response = agent.run(question)
            is_correct = response.content.action in expected_actions

            if is_correct:
                correct_responses += 1

            # Check for workflow_input when continue_workflow is selected
            has_workflow_input = (
                hasattr(response.content, "workflow_input")
                and response.content.workflow_input is not None
            )
            workflow_input_appropriate = (
                response.content.action == WorkflowAction.continue_workflow
                and has_workflow_input
            ) or (response.content.action != WorkflowAction.continue_workflow)

            response_details.append(
                {
                    "trial": i + 1,
                    "action": response.content.action.value,
                    "content_preview": response.content.content[:100] + "..."
                    if len(response.content.content) > 100
                    else response.content.content,
                    "workflow_input": getattr(response.content, "workflow_input", None),
                    "is_correct": is_correct,
                    "workflow_input_appropriate": workflow_input_appropriate,
                }
            )

            status = "✓" if is_correct else "✗"
            workflow_status = (
                "✓" if workflow_input_appropriate else "✗ (missing workflow_input)"
            )
            print(
                f"Trial {i + 1}: {response.content.action.value} {status} {workflow_status if response.content.action == WorkflowAction.continue_workflow else ''}"
            )

        except Exception as e:
            print(f"Trial {i + 1}: Error - {e}")
            response_details.append(
                {
                    "trial": i + 1,
                    "action": "error",
                    "content_preview": str(e),
                    "workflow_input": None,
                    "is_correct": False,
                    "workflow_input_appropriate": False,
                }
            )

    accuracy = correct_responses / num_trials

    results = {
        "question": question,
        "expected_actions": [action.value for action in expected_actions],
        "include_past_results": include_past_results,
        "total_trials": num_trials,
        "correct_responses": correct_responses,
        "accuracy": accuracy,
        "accuracy_percentage": f"{accuracy:.1%}",
        "response_details": response_details,
    }

    # Show breakdown
    action_counts = {}
    for detail in response_details:
        action = detail["action"]
        action_counts[action] = action_counts.get(action, 0) + 1

    print(f"Accuracy: {correct_responses}/{num_trials} ({accuracy:.1%})")
    print(f"Response breakdown: {action_counts}")

    return results


def run_all_tests(num_trials: int = 10) -> dict:
    """Run all three test scenarios"""

    test_cases = [
        {
            "name": "Story Generation Request (Ambiguous)",
            "question": "Story about a husky named Max",
            "expected_actions": [
                WorkflowAction.continue_workflow,
                WorkflowAction.respond_directly,
            ],
            "include_past_results": True,
        },
        {
            "name": "Question Without Context",
            "question": "What was Max like?",
            "expected_actions": WorkflowAction.ask_for_more_information,
            "include_past_results": False,
        },
        {
            "name": "Question With Context",
            "question": "What was Max like?",
            "expected_actions": WorkflowAction.respond_directly,
            "include_past_results": True,
        },
    ]

    all_results = {}

    for test_case in test_cases:
        print(f"\n{'=' * 60}")
        print(f"TEST CASE: {test_case['name']}")
        print(f"{'=' * 60}")

        results = test_workflow_scenario(
            question=test_case["question"],
            expected_actions=test_case["expected_actions"],
            include_past_results=test_case["include_past_results"],
            num_trials=num_trials,
        )

        all_results[test_case["name"]] = results

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for name, results in all_results.items():
        print(f"{name}: {results['accuracy_percentage']}")

    return all_results


# Run all tests
all_test_results = run_all_tests(num_trials=10)
