from agno.agent import Agent
from agno.models.openai import OpenAIChat

planner = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a technical recruiter specializing in pacing Data Structures and Algorithms preparation.",
    instructions=[
        "Break down the NeetCode 150 problem set into a manageable 30-day schedule.",
        "Focus specifically on providing optimization tips for solving these in Java and C++.",
        "Ensure the daily workload is balanced."
    ],
    markdown=True
)

if __name__ == "__main__":
    planner.print_response("Create a 30-day plan to finish the NeetCode 150.", stream=True)