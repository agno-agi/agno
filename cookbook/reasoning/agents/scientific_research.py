from agno.agent import Agent
from agno.models.openai import OpenAIChat

task = (
    "Read the following abstract of a scientific paper and provide a critical evaluation of its methodology,"
    "results, conclusions, and any potential biases or flaws:\n\n"
    "Abstract: This study examines the effect of a new teaching method on student performance in mathematics. "
    "A sample of 30 students was selected from a single school and taught using the new method over one semester. "
    "The results showed a 15% increase in test scores compared to the previous semester. "
    "The study concludes that the new teaching method is effective in improving mathematical performance among high school students."
)

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)
reasoning_agent.print_response(task, stream=True, show_full_reasoning=True)
