"""
Knowledge Search with AgentOSClient

This example demonstrates how to search the knowledge base
using AgentOSClient.

Prerequisites:
1. Start an AgentOS server with knowledge base configured
2. Upload some content to the knowledge base
3. Run this script: python 05_knowledge_search.py
"""

import asyncio

from agno.client import AgentOSClient


async def main():
    client = AgentOSClient(base_url="http://localhost:7777")

    print("=" * 60)
    print("Knowledge Search")
    print("=" * 60)

    # Get knowledge configuration
    print("\n1. Getting knowledge config...")
    try:
        config = await client.get_knowledge_config()
        print(
            f"   Available readers: {config.readers if hasattr(config, 'readers') else 'N/A'}"
        )
        print(
            f"   Available chunkers: {config.chunkers if hasattr(config, 'chunkers') else 'N/A'}"
        )
    except Exception as e:
        print(f"   Knowledge not configured: {e}")
        return

    # List existing content
    print("\n2. Listing content...")
    try:
        content = await client.list_knowledge_content()
        print(f"   Found {len(content.data)} content items")
        for item in content.data[:5]:
            print(
                f"   - {item.id}: {item.name if hasattr(item, 'name') else 'Unnamed'}"
            )
    except Exception as e:
        print(f"   Error listing content: {e}")

    # Search knowledge base
    print("\n3. Searching knowledge base...")
    try:
        results = await client.search_knowledge(
            query="What is Agno?",
            limit=5,
        )
        print(f"   Found {len(results.data)} results")
        for result in results.data:
            content_preview = (
                str(result.content)[:100] if hasattr(result, "content") else "N/A"
            )
            print(f"   - Score: {result.score if hasattr(result, 'score') else 'N/A'}")
            print(f"     Content: {content_preview}...")
    except Exception as e:
        print(f"   Error searching: {e}")


if __name__ == "__main__":
    asyncio.run(main())
