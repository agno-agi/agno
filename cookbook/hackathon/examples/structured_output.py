from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field


# Define a Pydantic model for the structured output
class MovieScript(BaseModel):
    setting: str = Field(
        ...,
        description="A richly detailed, atmospheric description of the movie's primary location and time period. Include sensory details and mood.",
    )
    genre: str = Field(
        ...,
        description="The film's primary and secondary genres (e.g., 'Sci-fi Thriller', 'Romantic Comedy'). Should align with setting and tone.",
    )
    name: str = Field(
        ...,
        description="An attention-grabbing, memorable title that captures the essence of the story and appeals to target audience.",
    )
    characters: List[str] = Field(
        ...,
        description="4-6 main characters with distinctive names and brief role descriptions (e.g., 'Sarah Chen - brilliant quantum physicist with a dark secret').",
    )
    storyline: str = Field(
        ...,
        description="A compelling three-sentence plot summary: Setup, Conflict, and Stakes. Hook readers with intrigue and emotion.",
    )


# Agent that uses JSON mode
json_mode_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    response_model=MovieScript,
)

# Agent that uses structured outputs
structured_output_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    response_model=MovieScript,
)

if __name__ == "__main__":
    json_mode_agent.print_response("Tokyo", stream=True)
    structured_output_agent.print_response("Ancient Rome", stream=True)
