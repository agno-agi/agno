"""Keep follow-up suggestions within a documentation assistant's scope.

Run with OPENAI_API_KEY set. Suggestions may be fewer than num_followups.
"""

from agno.agent import Agent, FollowupConfig
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Help with Python documentation. Decline unrelated requests briefly.",
    followups=True,
    num_followups=3,
    followup_config=FollowupConfig(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        instructions="Suggest only Python documentation questions. Do not repeat an out-of-scope request.",
    ),
)

if __name__ == "__main__":
    response = agent.run("Write a sea poem.")
    print(response.content)
    print("Follow-ups:", response.followups)
