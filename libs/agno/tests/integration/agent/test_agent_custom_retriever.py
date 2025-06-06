from agno.agent import Agent
from agno.models.openai import OpenAIChat


def test_agent_with_custom_retriever():
    def custom_retriever(**kwargs):
        return ["Paris is the capital of France"]

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        retriever=custom_retriever,
        add_references=True,
    )
    response = agent.run("What is the capital of France?")
    assert response.extra_data.references[0].references == ["Paris is the capital of France"]
    assert "Paris is the capital of France" in response.messages[0].content


def test_agent_with_custom_retriever_error():
    def custom_retriever(**kwargs):
        raise Exception("Test error")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        retriever=custom_retriever,
        add_references=True,
    )
    response = agent.run("What is the capital of France?")
    assert response.extra_data is None, "There should be no references"
    assert "<references>" not in response.messages[0].content


def test_agent_with_custom_retriever_search_knowledge_error():
    def custom_retriever(**kwargs):
        raise Exception("Test error")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        retriever=custom_retriever,
        search_knowledge=True,
        debug_mode=True,
    )
    response = agent.run("Search my knowledge base for information about the capital of France")
    assert response.extra_data is None, "There should be no references"
    assert response.tools[0].tool_name == "search_knowledge_base"
    assert response.content is not None
