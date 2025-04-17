"""Run `pip install openai agno` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.eval.perf import PerfEval

def simple_response():
    agent = Agent(model=OpenAIChat(id='gpt-4o-mini'), system_message='Be concise, reply with one sentence.', add_history_to_messages=True)
    response_1 = agent.run('What is the capital of France?')
    print(response_1.content)
    response_2 = agent.run('How many people live there?')
    print(response_2.content)
    return response_2.content


simple_response_perf = PerfEval(func=simple_response, num_iterations=1, warmup_runs=0)

if __name__ == "__main__":
    simple_response_perf.run(print_results=True)
