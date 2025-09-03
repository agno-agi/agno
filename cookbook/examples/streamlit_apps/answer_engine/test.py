from agents import get_sage

sage = get_sage()

if __name__ == "__main__":
    sage.show_tool_calls = True
    sage.print_response("Tell me about the tarrifs the US is imposing", stream=True)
