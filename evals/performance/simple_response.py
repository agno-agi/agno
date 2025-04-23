"""Run `pip install openai agno memory_profiler` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.eval.perf import PerfEval

def simple_response():
    agent = Agent(model=OpenAIChat(id='gpt-4o-mini'), system_message='Be concise, reply with one sentence.')
    response = agent.run('What is the capital of France?')
    print(response.content)
    return response


simple_response_perf = PerfEval(func=simple_response, num_iterations=1, warmup_runs=0)

if __name__ == "__main__":
    simple_response_perf.run(print_results=True)
