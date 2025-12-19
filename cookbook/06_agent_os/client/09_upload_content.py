"""
Uploading Content to Knowledge Base with AgentOSClient

This example demonstrates how to upload documents and content
to the knowledge base using AgentOSClient.

Prerequisites:
1. Start an AgentOS server with knowledge base configured
2. Run this script: python 09_upload_content.py
"""

import asyncio

from agno.client import AgentOSClient


async def upload_text_content():
    """Upload text content to the knowledge base."""
    print("=" * 60)
    print("Uploading Text Content")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    # Text content to upload
    content = """
    # Agno Framework Guide
    
    Agno is a powerful framework for building AI agents and teams.
    
    ## Key Features
    - Agent creation with custom tools
    - Team coordination for complex tasks
    - Workflow automation
    - Knowledge base integration
    - Memory management
    
    ## Getting Started
    1. Install agno: pip install agno
    2. Create an agent with a model
    3. Add tools for specific capabilities
    4. Deploy with AgentOS
    """

    try:
        print("Uploading text content...")

        # Upload the content using text_content parameter
        result = await client.upload_knowledge_content(
            text_content=content,
            name="Agno Guide",
            description="A guide to the Agno framework",
        )

        print("\nUpload successful!")
        print(f"Content ID: {result.id}")
        print(f"Status: {result.status}")

        # Check status
        if result.id:
            print("\nChecking processing status...")
            status = await client.get_content_status(result.id)
            print(f"Status: {status.status}")
            print(f"Message: {status.status_message}")

    except Exception as e:
        print(f"Error uploading: {e}")
        if hasattr(e, "response"):
            print(f"Response: {e.response.text}")


async def list_uploaded_content():
    """List all uploaded content."""
    print("\n" + "=" * 60)
    print("Listing Uploaded Content")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    try:
        content = await client.list_knowledge_content()
        print(f"\nFound {len(content.data)} content items")

        for item in content.data:
            print(f"\n- ID: {item.id}")
            print(f"  Name: {item.name}")
            print(f"  Status: {item.status}")
            print(f"  Type: {item.type}")

    except Exception as e:
        print(f"Error listing content: {e}")


async def search_uploaded_content():
    """Search the knowledge base after uploading."""
    print("\n" + "=" * 60)
    print("Searching Knowledge Base")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    try:
        # Search for content
        results = await client.search_knowledge(
            query="What is Agno?",
            limit=5,
        )

        print(f"\nFound {len(results.data)} results")

        for result in results.data:
            content_preview = (
                str(result.content)[:150] if hasattr(result, "content") else "N/A"
            )
            print(f"\n- Content: {content_preview}...")

    except Exception as e:
        print(f"Error searching: {e}")


async def delete_content():
    """Delete uploaded content."""
    print("\n" + "=" * 60)
    print("Deleting Content")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    try:
        # List content first
        content = await client.list_content()
        if not content.data:
            print("No content to delete")
            return

        # Delete the first item (for demo purposes)
        content_id = content.data[0].id
        print(f"Deleting content: {content_id}")

        await client.delete_content(content_id)
        print("Content deleted successfully")

        # Verify deletion
        content_after = await client.list_content()
        print(f"Remaining content items: {len(content_after.data)}")

    except Exception as e:
        print(f"Error deleting content: {e}")
        if hasattr(e, "response"):
            print(f"Response: {e.response.text}")


async def main():
    await upload_text_content()
    await list_uploaded_content()
    await search_uploaded_content()
    # Uncomment to test deletion:
    # await delete_content()


if __name__ == "__main__":
    asyncio.run(main())
