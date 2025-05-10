import os
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.memory.v2.db.mem0 import Mem0Memory
from rich.pretty import pprint
from mem0 import Memory, MemoryClient

mem0_mode = 'managed'
user_id = 'alice'

if mem0_mode == 'managed':
    client = MemoryClient(api_key=os.getenv('MEM0_API_KEY'))
else:
    config = {
        'graph_store': {
            'provider': 'neo4j',
            'config': {
                'url': 'bolt://localhost:7687',
                'username': 'neo4j',
                'password': '00000000',
            }
        },
        'embedder': {
            'provider': 'huggingface',
            'config': {
                'model': 'sentence-transformers/all-MiniLM-L6-v2',
                'embedding_dims': 384,
            }
        },
        'vector_store': {
            'provider': 'chroma',
            'config': {
                'path': 'tmp/mme0.chroma',
                'collection_name': 'memories',
            }
        },
    }
    client = Memory.from_config(config)

memory = Mem0Memory(client=client, user_id=user_id)
agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    user_id=user_id,
    memory=memory,
    enable_user_memories=True,
    add_history_to_messages=True,
)

if __name__ == '__main__':
    agent.print_response('Alice wants to date Bob. Show some recommended movies.')
    memories = memory.get_user_memories(user_id=user_id)
    pprint(memories)
