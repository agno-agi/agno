from typing import List

from agno.agent import Agent, RunResponse  # noqa
from agno.models.qwen import Qwen
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


class TechArticle(BaseModel):
    title: str = Field(..., description="Provide an engaging title for the tech article")
    summary: str = Field(..., description="Brief summary of the article in 2-3 sentences")
    category: str = Field(
        ...,
        description="Article category, such as: AI, Cloud Computing, IoT, Blockchain, etc.",
    )
    key_points: List[str] = Field(..., description="3-5 key points of the article")
    target_audience: str = Field(..., description="Target reader demographic")
    estimated_reading_time: str = Field(..., description="Estimated reading time")


json_mode_agent = Agent(
    model=Qwen(id="qwen-max"),
    description="You are a professional tech writing assistant that helps people create structured outlines for technology articles.",
    response_model=TechArticle,
    use_json_mode=True,
)

# Get the response in a variable
json_mode_response: RunResponse = json_mode_agent.run("Applications of Large Language Models in Customer Service")
pprint(json_mode_response.content)

# json_mode_agent.print_response("Applications of Large Language Models in Customer Service") 