from textwrap import dedent

from agno.agent import Agent, RunOutput  # noqa
from agno.models.ibm import WatsonX
from agno.tools.reasoning import ReasoningTools

"""🧠 Problem-Solving Reasoning Agent

This example shows how to create an agent that uses the ReasoningTools to solve
complex problems through step-by-step reasoning. The agent breaks down questions,
analyzes intermediate results, and builds structured reasoning paths to arrive at
well-justified conclusions.

Example prompts to try:
- "Solve this logic puzzle: A man has to take a fox, a chicken, and a sack of grain across a river."
- "Is it better to rent or buy a home given current interest rates?"
- "Evaluate the pros and cons of remote work versus office work."
- "How would increasing interest rates affect the housing market?"
- "What's the best strategy for saving for retirement in your 30s?"
"""


reasoning_agent = Agent(
    model=WatsonX(id="meta-llama/llama-3-3-70b-instruct"),
    tools=[ReasoningTools(add_instructions=True)],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠

        Your approach to problems:
        1. First, break down complex questions into component parts
        2. Clearly state your assumptions
        3. Develop a structured reasoning path
        4. Consider multiple perspectives
        5. Evaluate evidence and counter-arguments
        6. Draw well-justified conclusions

        When solving problems:
        - Use explicit step-by-step reasoning
        - Identify key variables and constraints
        - Explore alternative scenarios
        - Highlight areas of uncertainty
        - Explain your thought process clearly
        - Consider both short and long-term implications
        - Evaluate trade-offs explicitly

        For quantitative problems:
        - Show your calculations
        - Explain the significance of numbers
        - Consider confidence intervals when appropriate
        - Identify source data reliability

        For qualitative reasoning:
        - Assess how different factors interact
        - Consider psychological and social dynamics
        - Evaluate practical constraints
        - Address value considerations
        \
    """),
    add_datetime_to_context=True,
    stream_events=True,
    markdown=True,
)

# Example usage with a complex reasoning problem
reasoning_agent.print_response(
    "Solve this logic puzzle: A man has to take a fox, a chicken, and a sack of grain across a river. "
    "The boat is only big enough for the man and one item. If left unattended together, the fox will "
    "eat the chicken, and the chicken will eat the grain. How can the man get everything across safely?",
    stream=True,
)

# # Economic analysis example
# reasoning_agent.print_response(
#     "Is it better to rent or buy a home given current interest rates, inflation, and market trends? "
#     "Consider both financial and lifestyle factors in your analysis.",
#     stream=True
# )

# # Strategic decision-making example
# reasoning_agent.print_response(
#     "A startup has $500,000 in funding and needs to decide between spending it on marketing or "
#     "product development. They want to maximize growth and user acquisition within 12 months. "
#     "What factors should they consider and how should they analyze this decision?",
#     stream=True
# )
