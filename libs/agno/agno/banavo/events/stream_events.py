class BaseBanavoStreamEvent:
    """Base class for Banavo's typed stream events (UI, metadata, agent observability).

    Subclassing this allows events yielded from agent tool functions to propagate
    through Agno's run_function_calls and _handle_model_response_chunk without
    being stringified or treated as plain tool output.
    """
