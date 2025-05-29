import { useState, useCallback, useRef } from "react";
import { EventType, BaseEvent } from "@ag-ui/client";

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: Date;
}

interface UseAGUIAgentOptions {
  agent: string;
  onStateUpdate?: (state: any) => void;
  onToolCall?: (toolName: string, args: any) => void;
}

export function useAGUIAgent(options: UseAGUIAgentOptions) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [state, setState] = useState<any>({});
  const currentMessageRef = useRef<{
    id: string;
    content: string;
  } | null>(null);

  const sendMessage = useCallback(async (content: string) => {
    // Add user message
    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    setIsStreaming(true);

    try {
      const response = await fetch("/api/agui", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          agent: options.agent,
          messages: [...messages, userMessage].map(msg => ({
            role: msg.role,
            content: msg.content,
          })),
          state,
          threadId: `thread-${Date.now()}`,
          runId: `run-${Date.now()}`,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("No response body");
      }

      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const eventData = line.slice(6);
            if (eventData.trim()) {
              try {
                const event: BaseEvent = JSON.parse(eventData);
                handleEvent(event);
              } catch (error) {
                console.error("Failed to parse SSE event:", error);
              }
            }
          }
        }
      }
    } catch (error) {
      console.error("Error sending message:", error);
    } finally {
      setIsStreaming(false);
      currentMessageRef.current = null;
    }
  }, [messages, state, options.agent]);

  const handleEvent = useCallback((event: BaseEvent) => {
    switch (event.type) {
      case EventType.TEXT_MESSAGE_START:
        // Start a new assistant message
        const newMessage: Message = {
          id: (event as any).messageId,
          role: "assistant",
          content: "",
          timestamp: new Date(),
        };
        currentMessageRef.current = {
          id: newMessage.id,
          content: "",
        };
        setMessages(prev => [...prev, newMessage]);
        break;

      case EventType.TEXT_MESSAGE_CONTENT:
        // Stream content to the current message
        if (currentMessageRef.current && currentMessageRef.current.id === (event as any).messageId) {
          const delta = (event as any).delta;
          currentMessageRef.current.content += delta;
          setMessages(prev => 
            prev.map(msg => 
              msg.id === currentMessageRef.current?.id
                ? { ...msg, content: currentMessageRef.current.content }
                : msg
            )
          );
        }
        break;

      case EventType.STATE_SNAPSHOT:
        // Update state from snapshot
        const newState = (event as any).snapshot;
        setState(newState);
        options.onStateUpdate?.(newState);
        break;

      case EventType.STATE_DELTA:
        // Apply state delta (would need JSON patch library)
        console.log("State delta received:", event);
        break;

      case EventType.TOOL_CALL_START:
        // Handle tool call
        const toolEvent = event as any;
        if (options.onToolCall) {
          options.onToolCall(toolEvent.toolCallName, {});
        }
        break;

      // Handle other event types as needed
    }
  }, [options]);

  return {
    messages,
    sendMessage,
    isStreaming,
    state,
    setState,
  };
} 