"""
Knowledge from Factory
======================
Pass a function as `knowledge` so the knowledge base is resolved
at runtime. When `update_knowledge=True`, the `add_to_knowledge`
tool can insert into the factory-resolved knowledge base.

This example shows both an Agent and a Team storing information
into knowledge that comes from a callable factory.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.team import Team

# ---------------------------------------------------------------------------
# In-memory knowledge store (for demonstration)
# ---------------------------------------------------------------------------


class InMemoryKnowledge:
    """Simple knowledge store that records inserts in memory."""

    def __init__(self):
        self.documents: list[dict] = []

    def build_context(self, **kwargs) -> str:
        return "Use add_to_knowledge to store information for later."

    def get_tools(self, **kwargs):
        return []

    async def aget_tools(self, **kwargs):
        return []

    def retrieve(self, query: str, **kwargs):
        return []

    async def aretrieve(self, query: str, **kwargs):
        return []

    def insert(self, name: str = "", text_content: str = "", reader=None, **kwargs):
        self.documents.append({"name": name, "content": text_content})
        print(f"--> Inserted into knowledge: {name}")
        return True

    def search(self, query: str, num_documents: int = 5, **kwargs):
        return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

knowledge_store = InMemoryKnowledge()


def knowledge_factory(run_context: RunContext):
    """Return the knowledge base from a factory."""
    print("--> Factory resolved knowledge")
    return knowledge_store


# ---------------------------------------------------------------------------
# Agent with factory knowledge
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_factory,
    update_knowledge=True,
    search_knowledge=False,
    cache_callables=False,
    instructions=[
        "You have an add_to_knowledge tool.",
        "When asked to store information, use the add_to_knowledge tool.",
    ],
)

# ---------------------------------------------------------------------------
# Team with factory knowledge
# ---------------------------------------------------------------------------

helper = Agent(
    name="Helper",
    model=OpenAIChat(id="gpt-4o-mini"),
)

team = Team(
    name="KnowledgeTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_factory,
    update_knowledge=True,
    search_knowledge=False,
    members=[helper],
    cache_callables=False,
    instructions=[
        "You have an add_to_knowledge tool.",
        "When asked to store information, use the add_to_knowledge tool.",
    ],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Agent: store fact via factory knowledge ===")
    agent.print_response(
        "Store this fact: Python was created by Guido van Rossum. "
        "Use the add_to_knowledge tool with query='python_creator' and result='Guido van Rossum'.",
        stream=True,
    )
    print(f"\n--> Documents stored: {len(knowledge_store.documents)}")

    print("\n=== Team: store fact via factory knowledge ===")
    team.print_response(
        "Store this fact: Agno is an agent framework. "
        "Use the add_to_knowledge tool with query='agno_description' and result='agent framework'.",
        stream=True,
    )
    print(f"\n--> Documents stored: {len(knowledge_store.documents)}")
