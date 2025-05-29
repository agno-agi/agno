"use client";
import React, { useState, useEffect, useRef } from "react";
import { useCopilotChat } from "@copilotkit/react-core";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export const SimpleChat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: input.trim(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await fetch("/api/copilotkit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          operationName: "generateCopilotResponse",
          variables: {
            data: {
              messages: [
                {
                  id: userMessage.id,
                  textMessage: {
                    role: "user",
                    content: userMessage.content,
                  },
                },
              ],
              threadId: "simple-chat-thread",
              agentSession: {
                agentName: "agenticChatAgent",
                threadId: "simple-chat-thread",
              },
              agentStates: [],
            },
          },
          query: `
            mutation generateCopilotResponse($data: GenerateCopilotResponseInput!) {
              generateCopilotResponse(data: $data) {
                threadId
                runId
                messages @stream {
                  __typename
                  ... on TextMessageOutput {
                    id
                    content @stream
                    role
                  }
                }
              }
            }
          `,
        }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantMessage: Message | null = null;

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const eventData = line.substring(6);
            if (eventData === "[DONE]") {
              break;
            }

            if (eventData.trim()) {
              try {
                const data = JSON.parse(eventData);
                const messages = data?.data?.generateCopilotResponse?.messages;
                if (messages && messages.length > 0) {
                  const msg = messages[0];
                  if (msg.__typename === "TextMessageOutput" && msg.role === "assistant") {
                    if (!assistantMessage) {
                      assistantMessage = {
                        id: msg.id,
                        role: "assistant",
                        content: "",
                      };
                      setMessages((prev) => [...prev, assistantMessage!]);
                    }
                    
                    // Update the assistant message content
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === msg.id ? { ...m, content: msg.content } : m
                      )
                    );
                  }
                }
              } catch (e) {
                console.error("Parse error:", e);
              }
            }
          }
        }
      }
    } catch (error) {
      console.error("Error sending message:", error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-2xl shadow-lg">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${
              message.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-[70%] rounded-lg p-3 ${
                message.role === "user"
                  ? "bg-blue-500 text-white"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              {message.content}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg p-3">
              <div className="flex space-x-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t p-4">
        <div className="flex space-x-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && sendMessage()}
            placeholder="Type a message..."
            className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={isLoading}
          />
          <button
            onClick={sendMessage}
            disabled={isLoading}
            className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}; 