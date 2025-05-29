"use client";
import React, { useState } from "react";
import "@copilotkit/react-ui/styles.css";
import "./style.css";
import {
  CopilotKit,
  useCopilotAction,
  useCopilotChat,
} from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import { SimpleChat } from "./simple-chat";

const AgenticChat: React.FC = () => {
  const [useCustomChat, setUseCustomChat] = useState(true); // Default to custom chat due to CopilotKit issue
  
  return (
    <CopilotKit
      runtimeUrl="/api/copilotkit"
      showDevConsole={true}
      // agent lock to the relevant agent
      agent="agenticChatAgent"
    >
      <div className="h-full flex flex-col">
        <div className="p-4 bg-gray-100 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Agentic Chat</h2>
          <button
            onClick={() => setUseCustomChat(!useCustomChat)}
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 text-sm"
          >
            Switch to {useCustomChat ? "CopilotChat" : "SimpleChat"}
          </button>
        </div>
        <div className="flex-1">
          {useCustomChat ? <SimpleChat /> : <Chat />}
        </div>
      </div>
    </CopilotKit>
  );
};

const Chat = () => {
  const [background, setBackground] = useState<string>(
    "--copilot-kit-background-color"
  );

  useCopilotAction({
    name: "change_background",
    description:
      "Change the background color of the chat. Can be anything that the CSS background attribute accepts. Regular colors, linear of radial gradients etc.",
    parameters: [
      {
        name: "background",
        type: "string",
        description: "The background. Prefer gradients.",
      },
    ],
    handler: ({ background }) => {
      console.log("Changing background to", background);
      setBackground(background);
    },
    followUp: false,
  });

  return (
    <div
      className="flex justify-center items-center h-full w-full"
      style={{ background }}
    >
      <div className="w-8/10 h-8/10 rounded-lg">
        <CopilotChat
          className="h-full rounded-2xl"
          labels={{ initial: "Hi, I'm an agent. Want to chat?" }}
        />
      </div>
    </div>
  );
};

export default AgenticChat;
