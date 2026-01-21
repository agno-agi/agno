from agno.agent import Agent
from agno.models.openai import OpenAIChat


def test_agent_with_custom_knowledge_retriever():
    def custom_knowledge_retriever(**kwargs):
        return ["Paris is the capital of France"]

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge_retriever=custom_knowledge_retriever,  # type: ignore
        add_knowledge_to_context=True,
    )
    response = agent.run("What is the capital of France?")
    assert response is not None and response.references is not None
    assert response.references[0].references == ["Paris is the capital of France"]


def test_agent_with_custom_knowledge_retriever_error():
    def custom_knowledge_retriever(**kwargs):
        raise Exception("Test error")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge_retriever=custom_knowledge_retriever,
        add_knowledge_to_context=True,
    )
    response = agent.run("What is the capital of France?")
    assert response.metadata is None, "There should be no references"
    assert "<references>" not in response.messages[0].content  # type: ignore


def test_agent_with_custom_knowledge_retriever_search_knowledge_error():
    def custom_knowledge_retriever(**kwargs):
        raise Exception("Test error")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge_retriever=custom_knowledge_retriever,
        search_knowledge=True,
        debug_mode=True,
        instructions="Always search the knowledge base for information before answering.",
    )
    response = agent.run("Search my knowledge base for information about the capital of France")
    assert response.metadata is None, "There should be no references"
    assert response.tools and response.tools[0].tool_name == "search_knowledge_base"
    assert response.content is not None
