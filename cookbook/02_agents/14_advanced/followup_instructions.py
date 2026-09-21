"""Keep follow-up suggestions within a documentation assistant's scope.

Run with OPENAI_API_KEY set. Suggestions may be fewer than num_followups.
"""

from agno.agent import Agent, FollowupConfig
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Help with Python documentation. Decline unrelated requests briefly.",
    followups=FollowupConfig(
        num_followups=3,
        model=OpenAIResponses(id="gpt-5.5"),
        instructions="Suggest only Python documentation questions. Do not repeat an out-of-scope request.",
    ),
)

if __name__ == "__main__":
    response = agent.run("Write a sea poem.")
    print(response.content)
    print("Follow-ups:", response.followups)
