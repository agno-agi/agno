"""Utility functions for the LangGraph adapter."""

import json
from typing import Any, Dict, List, Optional


def build_messages_with_history(input: Any, history: Optional[List[Dict[str, Any]]] = None) -> List[Any]:
    """Build a LangChain message list with conversation history prepended.

    Converts the generic history format from BaseExternalAgent into proper
    LangChain message types (HumanMessage, AIMessage, ToolMessage) with
    correct tool_call linking.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    messages: List[Any] = []
    if history:
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # Convert from stored format {"type":"function","function":{"name","arguments"}}
                    # to LangChain format {"id","name","args"}
                    lc_tool_calls = []
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        args = func.get("arguments", "{}")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, TypeError):
                                args = {"input": args}
                        lc_tool_calls.append(
                            {
                                "id": tc.get("id", ""),
                                "name": func.get("name", ""),
                                "args": args,
                            }
                        )
                    messages.append(AIMessage(content=msg.get("content", ""), tool_calls=lc_tool_calls))
                else:
                    messages.append(AIMessage(content=msg["content"]))
            elif msg["role"] == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                messages.append(ToolMessage(content=msg["content"], tool_call_id=tool_call_id))
    if input is not None:
        messages.append(HumanMessage(content=str(input)))
    return messages
