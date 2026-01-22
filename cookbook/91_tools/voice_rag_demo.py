"""
ElevenLabs Voice RAG - Real-time Voice Chat Demo

This standalone script demonstrates real-time voice conversation with RAG.
It creates a voice agent from your content and opens a browser widget for
speech-to-speech conversation.

Requirements:
    pip install agno httpx

Environment Variables:
    ELEVEN_LABS_API_KEY: Your ElevenLabs API key

Usage:
    # With a document file
    python voice_rag_demo.py --file path/to/document.pdf --name "My Assistant"

    # With a URL
    python voice_rag_demo.py --url https://example.com/docs --name "Doc Bot"

    # With inline text
    python voice_rag_demo.py --text "Your content here..." --name "Info Bot"

    # Interactive mode
    python voice_rag_demo.py --interactive
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

# Add the libs path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "libs" / "agno"))

from agno.tools.eleven_labs_voice_rag import ElevenLabsVoiceRAGTools


def create_voice_agent_from_file(
    file_path: str,
    agent_name: str,
    system_prompt: str = None,
    language: str = "en",
    llm: str = "qwen3-30b-a3b",
) -> dict:
    """Create a voice agent from a file."""

    tools = ElevenLabsVoiceRAGTools(
        language=language,
        llm=llm,
        auto_compute_rag_index=True,
    )

    # Upload document
    print(f"📄 Uploading document: {file_path}")
    upload_result = json.loads(tools.upload_document(file_path))

    if not upload_result.get("success"):
        return {"error": upload_result.get("error", "Upload failed")}

    document_id = upload_result["document_id"]
    print(f"✅ Document uploaded: {document_id}")

    # Create agent
    default_prompt = f"""You are a helpful assistant that answers questions based on the uploaded document.
Be concise, accurate, and helpful. If you don't know something, say so.
Always base your answers on the information from the knowledge base."""

    print(f"🤖 Creating voice agent: {agent_name}")
    agent_result = json.loads(
        tools.create_voice_agent(
            name=agent_name,
            system_prompt=system_prompt or default_prompt,
            first_message=f"Hello! I'm {agent_name}. How can I help you today?",
            knowledge_base_ids=[document_id],
            language=language,
            llm=llm,
        )
    )

    return agent_result


def create_voice_agent_from_url(
    url: str,
    agent_name: str,
    system_prompt: str = None,
    language: str = "en",
    llm: str = "qwen3-30b-a3b",
) -> dict:
    """Create a voice agent from a URL."""

    tools = ElevenLabsVoiceRAGTools(
        language=language,
        llm=llm,
        auto_compute_rag_index=True,
    )

    # Create from URL
    print(f"🔗 Creating knowledge base from URL: {url}")
    url_result = json.loads(tools.create_from_url(url))

    if not url_result.get("success"):
        return {"error": url_result.get("error", "URL creation failed")}

    document_id = url_result["document_id"]
    print(f"✅ Document created: {document_id}")

    # Create agent
    default_prompt = f"""You are a helpful assistant that answers questions based on the content from {url}.
Be concise, accurate, and helpful. If you don't know something, say so."""

    print(f"🤖 Creating voice agent: {agent_name}")
    agent_result = json.loads(
        tools.create_voice_agent(
            name=agent_name,
            system_prompt=system_prompt or default_prompt,
            first_message=f"Hello! I'm {agent_name}. How can I help you today?",
            knowledge_base_ids=[document_id],
            language=language,
            llm=llm,
        )
    )

    return agent_result


def create_voice_agent_from_text(
    text: str,
    agent_name: str,
    system_prompt: str = None,
    language: str = "en",
    llm: str = "qwen3-30b-a3b",
) -> dict:
    """Create a voice agent from raw text."""

    tools = ElevenLabsVoiceRAGTools(
        language=language,
        llm=llm,
        auto_compute_rag_index=True,
    )

    # Create from text
    print(f"📝 Creating knowledge base from text...")
    text_result = json.loads(
        tools.create_from_text(text, name=f"{agent_name} Knowledge")
    )

    if not text_result.get("success"):
        return {"error": text_result.get("error", "Text creation failed")}

    document_id = text_result["document_id"]
    print(f"✅ Document created: {document_id}")

    # Create agent
    default_prompt = """You are a helpful assistant that answers questions based on the provided information.
Be concise, accurate, and helpful. If you don't know something, say so."""

    print(f"🤖 Creating voice agent: {agent_name}")
    agent_result = json.loads(
        tools.create_voice_agent(
            name=agent_name,
            system_prompt=system_prompt or default_prompt,
            first_message=f"Hello! I'm {agent_name}. How can I help you today?",
            knowledge_base_ids=[document_id],
            language=language,
            llm=llm,
        )
    )

    return agent_result


def interactive_mode():
    """Interactive mode for creating voice agents."""

    print("\n" + "=" * 60)
    print("🎤 ElevenLabs Voice RAG - Interactive Mode")
    print("=" * 60)

    # Check API key
    if not os.getenv("ELEVEN_LABS_API_KEY") and not os.getenv("ELEVENLABS_API_KEY"):
        print("\n❌ Error: ELEVEN_LABS_API_KEY environment variable not set")
        print("Set it with: export ELEVEN_LABS_API_KEY='your-api-key'")
        return

    print("\nChoose content source:")
    print("1. File (PDF, TXT, DOCX)")
    print("2. URL")
    print("3. Text input")

    choice = input("\nEnter choice (1-3): ").strip()

    if choice == "1":
        file_path = input("Enter file path: ").strip()
        if not Path(file_path).exists():
            print(f"❌ File not found: {file_path}")
            return
        agent_name = input("Enter agent name: ").strip() or "Document Assistant"
        result = create_voice_agent_from_file(file_path, agent_name)

    elif choice == "2":
        url = input("Enter URL: ").strip()
        agent_name = input("Enter agent name: ").strip() or "Web Assistant"
        result = create_voice_agent_from_url(url, agent_name)

    elif choice == "3":
        print("Enter text content (end with empty line):")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        text = "\n".join(lines)
        agent_name = input("Enter agent name: ").strip() or "Text Assistant"
        result = create_voice_agent_from_text(text, agent_name)

    else:
        print("Invalid choice")
        return

    # Handle result
    if result.get("error"):
        print(f"\n❌ Error: {result['error']}")
        return

    print("\n" + "=" * 60)
    print("✅ Voice Agent Created Successfully!")
    print("=" * 60)
    print(f"\nAgent ID: {result.get('agent_id')}")
    print(f"Name: {result.get('name')}")
    print(f"Language: {result.get('language')}")
    print(f"LLM: {result.get('llm')}")
    print(f"\n🔗 Dashboard: {result.get('dashboard_url')}")
    print(f"\n📋 Embed Code:\n{result.get('embed_code')}")
    print(f"\n📝 Instructions: {result.get('message')}")

    # Open in browser
    open_browser = input("\nOpen dashboard in browser? (y/n): ").strip().lower()
    if open_browser == "y":
        dashboard_url = result.get("dashboard_url")
        if dashboard_url:
            print(f"\n🌐 Opening {dashboard_url}")
            webbrowser.open(dashboard_url)
            print("\n⚙️  Enable 'Public Access' in Security tab, then embed the widget!")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Create ElevenLabs Voice RAG agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python voice_rag_demo.py --file doc.pdf --name "Doc Bot"
  python voice_rag_demo.py --url https://docs.python.org --name "Python Helper"
  python voice_rag_demo.py --text "Company info..." --name "Info Bot"
  python voice_rag_demo.py --interactive
        """,
    )

    parser.add_argument("--file", help="Path to document file")
    parser.add_argument("--url", help="URL to create knowledge from")
    parser.add_argument("--text", help="Text content for knowledge base")
    parser.add_argument("--name", default="Voice Assistant", help="Agent name")
    parser.add_argument(
        "--language", default="en", help="Language code (en, hi, es, etc)"
    )
    parser.add_argument("--llm", default="qwen3-30b-a3b", help="LLM model")
    parser.add_argument("--prompt", help="Custom system prompt")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument(
        "--open-browser", action="store_true", help="Open widget in browser"
    )

    args = parser.parse_args()

    # Check API key
    if not os.getenv("ELEVEN_LABS_API_KEY") and not os.getenv("ELEVENLABS_API_KEY"):
        print("❌ Error: ELEVEN_LABS_API_KEY environment variable not set")
        print("Set it with: export ELEVEN_LABS_API_KEY='your-api-key'")
        sys.exit(1)

    if args.interactive:
        interactive_mode()
        return

    # Determine content source
    if args.file:
        if not Path(args.file).exists():
            print(f"❌ File not found: {args.file}")
            sys.exit(1)
        result = create_voice_agent_from_file(
            args.file, args.name, args.prompt, args.language, args.llm
        )
    elif args.url:
        result = create_voice_agent_from_url(
            args.url, args.name, args.prompt, args.language, args.llm
        )
    elif args.text:
        result = create_voice_agent_from_text(
            args.text, args.name, args.prompt, args.language, args.llm
        )
    else:
        parser.print_help()
        print("\n❌ Please provide --file, --url, --text, or --interactive")
        sys.exit(1)

    # Handle result
    if result.get("error"):
        print(f"\n❌ Error: {result['error']}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ Voice Agent Created Successfully!")
    print("=" * 60)
    print(f"\nAgent ID: {result.get('agent_id')}")
    print(f"Name: {result.get('name')}")
    print(f"Language: {result.get('language')}")
    print(f"LLM: {result.get('llm')}")
    print(f"Knowledge Base: {result.get('knowledge_base_count')} document(s)")
    print(f"\n🔗 Widget URL: {result.get('widget_url')}")

    if args.open_browser:
        widget_url = result.get("widget_url")
        if widget_url:
            print(f"\n🌐 Opening {widget_url}")
            webbrowser.open(widget_url)

    print("\n🎤 Open the widget URL to start a voice conversation!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
