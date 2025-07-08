from typing import Iterator

from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import Workflow


class CacheWorkflow(Workflow):
    description: str = "A workflow that caches previous outputs"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    def run(self, message: str) -> Iterator[RunResponse]:
        logger.info(f"Checking cache for '{message}'")
        if self.session_state.get(message):
            logger.info(f"Cache hit for '{message}'")
            yield RunResponse(
                run_id=self.run_id, content=self.session_state.get(message)
            )
            return

        logger.info(f"Cache miss for '{message}'")
        yield from self.agent.run(message, stream=True)
        self.session_state[message] = self.agent.run_response.content


if __name__ == "__main__":
    workflow = CacheWorkflow()
    # Run workflow
    response: Iterator[RunResponse] = workflow.run(message="Tell me a joke.")
    # Print the response
    pprint_run_response(response, markdown=True, show_time=True)
    # Run workflow again
    response: Iterator[RunResponse] = workflow.run(message="Tell me a joke.")
    # Print the response
    pprint_run_response(response, markdown=True, show_time=True)
