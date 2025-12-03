"""CLI interface for Docs Assistant."""

import sys

from agents.docs_assistant import get_docs_assistant

docs_assistant = get_docs_assistant()


def ask(query: str, session_id: str = "default"):
    """Ask a question about the documentation."""
    return docs_assistant.print_response(query, session_id=session_id, stream=True)


def interactive_mode():
    """Run in interactive mode for continuous queries."""
    print("\nDocs Assistant")
    print("=" * 50)
    print("Commands:")
    print("  <question>  - Ask a question")
    print("  exit        - Quit")
    print("=" * 50)

    session_id = "interactive"

    while True:
        try:
            user_input = input("\n> ").strip()

            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("Goodbye!")
                break

            docs_assistant.print_response(
                user_input, session_id=session_id, stream=True
            )

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # CLI mode: python -m app.cli "How do I deploy?"
        ask(" ".join(sys.argv[1:]))
    else:
        # Interactive mode
        interactive_mode()
