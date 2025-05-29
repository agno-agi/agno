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
      const response = await fetch("/api/agui", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: [
            {
              id: userMessage.id,
              role: userMessage.role,
              content: userMessage.content,
            },
          ],
          threadId: "simple-chat-thread",
          runId: `run-${Date.now()}`,
          state: {},
          tools: [],
          context: [],
          forwardedProps: {},
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
                const event = JSON.parse(eventData);
                
                switch (event.type) {
                  case "TEXT_MESSAGE_START":
                    assistantMessage = {
                      id: event.messageId,
                      role: "assistant",
                      content: "",
                    };
                    setMessages((prev) => [...prev, assistantMessage!]);
                    break;
                    
                  case "TEXT_MESSAGE_CONTENT":
                    if (assistantMessage && event.delta) {
                      assistantMessage.content += event.delta;
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === assistantMessage!.id 
                            ? { ...m, content: assistantMessage!.content } 
                            : m
                        )
                      );
                    }
                    break;
                    
                  case "RUN_ERROR":
                    console.error("Run error:", event.message);
                    setMessages((prev) => [...prev, {
                      id: `error-${Date.now()}`,
                      role: "assistant",
                      content: `Error: ${event.message || "Unknown error occurred"}`
                    }]);
                    break;
                }
              } catch (e) {
                console.error("Parse error:", e, eventData);
              }
            }
          }
        }
      }
    } catch (error) {
      console.error("Error sending message:", error);
      // Add error message
      setMessages((prev) => [...prev, {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again."
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  // Filter out any empty messages
  const displayMessages = messages.filter(msg => msg.content && msg.content.trim());

  return (
    <div className="flex flex-col h-full bg-white rounded-2xl shadow-lg">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {displayMessages.length === 0 && !isLoading && (
          <div className="text-center text-gray-500 mt-8">
            Start a conversation by typing a message below.
          </div>
        )}
        {displayMessages.map((message) => (
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
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg p-3">
              <div className="flex space-x-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0.1s" }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
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
            className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-black"
            disabled={isLoading}
            style={{ color: '#000', WebkitTextFillColor: '#000' }}
          />
          <button
            onClick={sendMessage}
            disabled={isLoading || !input.trim()}
            className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}; 