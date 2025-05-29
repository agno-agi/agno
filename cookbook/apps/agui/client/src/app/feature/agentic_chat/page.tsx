"use client";
import React, { useState, useEffect, useCallback } from "react";
import "@copilotkit/react-ui/styles.css";
import "./style.css";
import "./input-fix.css";
import "./empty-message-fix.css";
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
      runtimeUrl="/api/agui"
      showDevConsole={false}
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
  
  // Use the chat hook to monitor messages
  const { isLoading } = useCopilotChat();
  const [hasUserInteracted, setHasUserInteracted] = useState(false);
  
  // Pass agent configuration through context
  const agentConfig = {
    agentName: "agenticChatAgent",
  };
  
  // Monitor for initial CopilotKit load and clean up empty messages
  useEffect(() => {
    // Check if CopilotKit has loaded and clean up any initial empty messages
    const checkAndCleanInitialMessages = () => {
      if (!hasUserInteracted) {
        const allMessages = document.querySelectorAll('.copilotKitMessage, [class*="Message"]');
        allMessages.forEach(msg => {
          const el = msg as HTMLElement;
          const text = el.textContent?.trim();
          // Hide if it's the default greeting and user hasn't interacted yet
          if (!text || text === "" || text === "Hello! How can I assist you today?") {
            el.style.display = 'none';
          }
        });
      }
    };
    
    // Run check multiple times during initial load
    const timers = [
      setTimeout(checkAndCleanInitialMessages, 100),
      setTimeout(checkAndCleanInitialMessages, 300),
      setTimeout(checkAndCleanInitialMessages, 500),
      setTimeout(checkAndCleanInitialMessages, 1000),
    ];
    
    // Monitor for user input to know when they've started interacting
    const handleUserInput = () => setHasUserInteracted(true);
    document.addEventListener('keydown', handleUserInput);
    document.addEventListener('click', handleUserInput);
    
    return () => {
      timers.forEach(clearTimeout);
      document.removeEventListener('keydown', handleUserInput);
      document.removeEventListener('click', handleUserInput);
    };
  }, [hasUserInteracted]);
  
  // Enhanced cleanup for empty message bubbles
  const cleanupEmptyMessages = useCallback(() => {
    // More comprehensive selectors
    const selectors = [
      '.copilotKitMessage',
      '.copilotKitMessages > div',
      '[class*="Message_root"]',
      '[class*="message"]',
      '[class*="Messages"] > div',
      '.copilotKitAssistantMessage',
      '.copilotKitUserMessage'
    ];
    
    selectors.forEach(selector => {
      const messageElements = document.querySelectorAll(selector);
      messageElements.forEach((element) => {
        const el = element as HTMLElement;
        const textContent = el.textContent?.trim();
        
        // Check various conditions for empty elements
        const isEmpty = !textContent || textContent === '' || textContent.length === 0;
        const hasOnlyWhitespace = textContent && /^\s*$/.test(textContent);
        const hasOnlyDots = textContent && /^[.• ]+$/.test(textContent);
        const isLoadingIndicator = el.querySelector('.animate-pulse, .animate-bounce, [class*="loading"]');
        const hasNoVisibleChildren = !el.querySelector('*:not(:empty)');
        const isDefaultGreeting = textContent === "Hello! How can I assist you today?";
        
        // Check if it's just a wrapper div with no meaningful content
        const isEmptyWrapper = el.children.length === 0 && isEmpty;
        
        // Hide if empty, loading, or default greeting without user interaction
        if (isEmpty || hasOnlyWhitespace || hasOnlyDots || isEmptyWrapper ||
            (isLoadingIndicator && textContent && textContent.length < 3) || 
            (!hasUserInteracted && isDefaultGreeting)) {
          el.style.setProperty('display', 'none', 'important');
          el.style.setProperty('visibility', 'hidden', 'important');
          el.style.setProperty('height', '0', 'important');
          el.style.setProperty('padding', '0', 'important');
          el.style.setProperty('margin', '0', 'important');
          el.style.setProperty('overflow', 'hidden', 'important');
        }
      });
    });
    
    // Also hide any trailing empty divs
    const messagesContainer = document.querySelector('.copilotKitMessages, [class*="Messages_root"]');
    if (messagesContainer) {
      const children = Array.from(messagesContainer.children);
      // Check from the end
      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i] as HTMLElement;
        if (!child.textContent?.trim() || child.textContent.trim() === "Hello! How can I assist you today?") {
          child.style.setProperty('display', 'none', 'important');
        } else {
          break; // Stop when we find a non-empty element
        }
      }
    }
  }, [hasUserInteracted]);

  // Run cleanup more aggressively
  useEffect(() => {
    // Initial cleanup
    cleanupEmptyMessages();
    
    // Multiple delayed cleanups to catch async renders
    const timeouts = [
      setTimeout(cleanupEmptyMessages, 50),
      setTimeout(cleanupEmptyMessages, 100),
      setTimeout(cleanupEmptyMessages, 200),
      setTimeout(cleanupEmptyMessages, 500),
    ];
    
    // Continuous monitoring
    const interval = setInterval(cleanupEmptyMessages, 250);
    
    return () => {
      timeouts.forEach(clearTimeout);
      clearInterval(interval);
    };
  }, [isLoading, cleanupEmptyMessages]);

  // Fix input visibility with more aggressive approach
  useEffect(() => {
    const fixInputVisibility = () => {
      // Target all possible input elements
      const selectors = [
        'textarea',
        'input[type="text"]',
        '[contenteditable="true"]',
        '.copilotKitInput textarea',
        '.copilotKitInput input',
        '[class*="Input"] textarea',
        '[class*="input"] textarea',
        '[aria-label*="message"]',
        '[placeholder*="message"]'
      ];
      
      selectors.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        elements.forEach((element) => {
          const el = element as HTMLElement;
          el.style.setProperty('color', '#000', 'important');
          el.style.setProperty('opacity', '1', 'important');
          el.style.setProperty('-webkit-text-fill-color', '#000', 'important');
          el.style.setProperty('caret-color', '#000', 'important');
          
          // Ensure there's a background for contrast
          const computedStyle = window.getComputedStyle(el);
          if (computedStyle.backgroundColor === 'rgba(0, 0, 0, 0)' || 
              computedStyle.backgroundColor === 'transparent') {
            el.style.setProperty('background-color', 'rgba(255, 255, 255, 0.9)', 'important');
          }
        });
      });
      
      // Also fix the input wrapper
      const inputWrappers = document.querySelectorAll('.copilotKitInput, [class*="Input_root"]');
      inputWrappers.forEach((wrapper) => {
        const el = wrapper as HTMLElement;
        el.style.setProperty('background-color', '#fff', 'important');
      });
    };
    
    // Fix immediately
    fixInputVisibility();
    
    // Fix after delays
    const timeouts = [
      setTimeout(fixInputVisibility, 100),
      setTimeout(fixInputVisibility, 500),
      setTimeout(fixInputVisibility, 1000),
    ];
    
    // Monitor for changes
    const observer = new MutationObserver(() => {
      fixInputVisibility();
    });
    
    observer.observe(document.body, { 
      childList: true, 
      subtree: true,
      attributes: true,
      attributeFilter: ['style', 'class']
    });
    
    // Also fix on focus
    document.addEventListener('focusin', fixInputVisibility);
    
    return () => {
      timeouts.forEach(clearTimeout);
      observer.disconnect();
      document.removeEventListener('focusin', fixInputVisibility);
    };
  }, []);

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
      <div className="w-8/10 h-8/10 rounded-lg copilot-chat-wrapper">
        <CopilotChat
          className="h-full rounded-2xl"
          labels={{ initial: "Hi, I'm an agent. Want to chat?" }}
        />
      </div>
    </div>
  );
};

export default AgenticChat;
