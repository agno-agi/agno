from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.response import RunResponse
from agno.utils.pprint import pprint_run_response
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    content: str = Field(description="The content that you need to give feedback on")
    feedback: str = Field(description="The feedback on the content")
    score: int = Field(description="The score of the content from 0 to 10")


class SelfEvaluationWorkflow(Workflow):
    description: str = "Self Evaluation Workflow"

    content_creator_agent: Agent = Agent(
        name="Content Creator",
        description="Content Creator Agent",
        instructions=[
            "You are a content creator intern that creates content for LinkedIn that have no experience in creating content. So you make a lot of mistakes.",
            "You are given a task and you need to create content for LinkedIn.",
            "You need to create content that is engaging and interesting.",
            "You need to create content that is relevant to the task.",
            "You do an ok job at creating content, but you need to improve your content based on the feedback.",
        ],
        model=OpenAIChat(id="gpt-4o"),
        debug_mode=True,
    )

    content_reviewer_agent: Agent = Agent(
        name="Content Reviewer",
        description="Content Reviewer Agent",
        instructions=[
            "You are a senior content reviewer agent that reviews content for LinkedIn and have a lot of experience in creating content.",
            "You are given a content and you need to review content for LinkedIn.",
            "You need to make sure the content is not too long and not too short.",
            "You need to make sure the content doesn't have any spelling or grammar mistakes.",
            "You need to make sure the content doesn't have a lot of emojis.",
            "You need to make sure the content is not too promotional and not too salesy.",
            "You need to make sure the content is not too technical and not too complex.",
        ],
        response_model=Feedback,
        model=OpenAIChat(id="gpt-4o"),
        debug_mode=True,
    )

    def run(self, topic: str) -> RunResponse:
        content_response = self.content_creator_agent.run(topic)
        max_tries = 3
        for _ in range(max_tries):
            feedback = self.content_reviewer_agent.run(content_response.content)
            if feedback.content and feedback.content.score > 8:
                break
            content_feedback_input = f"Here is the feedback: {feedback.content.feedback if feedback.content else ''} for your content {content_response.content if content_response.content else ''}. \nPlease improve the content based on the feedback."
            content_response = self.content_creator_agent.run(content_feedback_input)
        return content_response


if __name__ == "__main__":
    self_evaluation_workflow = SelfEvaluationWorkflow()
    response = self_evaluation_workflow.run(
        topic="create a post about the latest trends in AI"
    )
    pprint_run_response(response)
