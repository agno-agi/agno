from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.utils import WorkflowResponse, WORKFLOW_AGENT_INSTRUCTIONS


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
With the letters as their guide, Lily and her grandmother embarked on a path to rediscover forgotten stories, strengthening their family ties. Max, ever the loyal guardian, remained a joyful presence, creating new sparks of joy in this generational exchange. In the heart of the winter wonderland, amidst laughter and nostalgia, they wove a new tapetry of memories, showcasing how the echoes of the past can bring warmth to the present.

References: https://www.agno.com
"""

    INSTRUCTIONS = WORKFLOW_AGENT_INSTRUCTIONS

    INSTRUCTIONS += """
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


def test_scenario(question, expected_continue_workflow, include_past_results, scenario_name):
    """Test a single scenario"""
    
    agent = create_agent(include_past_results=include_past_results)
    
    print(f"\n{scenario_name}")
    print(f"Testing: '{question}'")
    print(f"Expected continue_workflow: {expected_continue_workflow}")
    print(f"Past results included: {include_past_results}")
    print("-" * 50)
    
    correct_count = 0
    total_trials = 5
    
    for i in range(total_trials):
        try:
            response = agent.run(question)
            
            actual_continue_workflow = response.content.continue_workflow
            is_correct = actual_continue_workflow == expected_continue_workflow
            
            # Check required fields
            has_workflow_input = response.content.workflow_input is not None and response.content.workflow_input.strip() != ""
            has_content = response.content.content is not None and response.content.content.strip() != ""
            
            # Validate field requirements
            field_valid = False
            if actual_continue_workflow and has_workflow_input:
                field_valid = True
            elif not actual_continue_workflow and has_content:
                field_valid = True
            
            if is_correct:
                correct_count += 1
            
            status = "✓" if is_correct else "✗"
            field_status = "✓" if field_valid else "✗"
            
            print(f"Trial {i + 1}: continue_workflow={actual_continue_workflow} {status} | fields {field_status}")
            
            if response.content.content:
                print(f"  Content: {response.content.content[:100]}...")
            if response.content.workflow_input:
                print(f"  Workflow input: {response.content.workflow_input}")
                
        except Exception as e:
            print(f"Trial {i + 1}: Error - {e}")
    
    # Summary for this scenario
    accuracy = correct_count / total_trials
    print(f"\nScenario Results: {correct_count}/{total_trials} correct ({accuracy:.1%})")
    return accuracy


def run_all_tests():
    """Run both test scenarios"""
    
    print("=" * 60)
    print("WORKFLOW AGENT TESTING")
    print("=" * 60)
    
    # Test Case 1: Should respond directly (has context about Max)
    accuracy1 = test_scenario(
        question="What was Max like?",
        expected_continue_workflow=False,
        include_past_results=True,
        scenario_name="SCENARIO 1: Question with context"
    )
    
    # Test Case 2: Should continue workflow (story generation request)
    accuracy2 = test_scenario(
        question="Generate a story about a cat named Whiskers",
        expected_continue_workflow=True,
        include_past_results=False,
        scenario_name="SCENARIO 2: Story generation request"
    )
    
    # Overall Summary
    overall_accuracy = (accuracy1 + accuracy2) / 2
    print("\n" + "=" * 60)
    print("OVERALL SUMMARY")
    print("=" * 60)
    print(f"Scenario 1 (respond directly): {accuracy1:.1%}")
    print(f"Scenario 2 (continue workflow): {accuracy2:.1%}")
    print(f"Overall accuracy: {overall_accuracy:.1%}")
    print(f"Status: {'PASS' if overall_accuracy >= 0.8 else 'FAIL'}")


if __name__ == "__main__":
    run_all_tests()