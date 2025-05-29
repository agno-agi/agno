import { createAgnoAgent } from "@/agno-http-agent";
import { NextRequest, NextResponse } from "next/server";
import { Observable } from "rxjs";
import { EventType, BaseEvent } from "@ag-ui/client";

// Create Agno HTTP agents for each feature
const agents = {
  agenticChatAgent: createAgnoAgent("agenticChatAgent"),
  agentiveGenerativeUIAgent: createAgnoAgent("agentiveGenerativeUIAgent"),
  humanInTheLoopAgent: createAgnoAgent("humanInTheLoopAgent"),
  predictiveStateUpdatesAgent: createAgnoAgent("predictiveStateUpdatesAgent"),
  sharedStateAgent: createAgnoAgent("sharedStateAgent"),
  toolBasedGenerativeUIAgent: createAgnoAgent("toolBasedGenerativeUIAgent"),
};

export const POST = async (req: NextRequest) => {
  try {
    const body = await req.json();
    
    // Log the entire request body to understand its structure
    console.log("[CopilotKit Route] Full request body:", JSON.stringify(body, null, 2));
    
    // Check if this is a GraphQL introspection query
    if (body.query && body.query.includes("__schema")) {
      console.log("[CopilotKit Route] GraphQL introspection query detected");
      // Return a minimal GraphQL introspection response
      return NextResponse.json({
        data: {
          __schema: {
            queryType: { name: "Query" },
            mutationType: { name: "Mutation" },
            subscriptionType: null,
            types: []
          }
        }
      });
    }
    
    // Extract the actual data from the GraphQL request
    const data = body?.variables?.data || body?.data || {};
    const properties = body?.variables?.properties || body?.properties || {};
    
    console.log("[CopilotKit Route] Extracted data:", {
      agent: data?.metadata?.agent,
      agentSession: data?.agentSession,
      messageCount: data?.messages?.length || 0,
      lastMessage: data?.messages?.[data?.messages?.length - 1],
    });

    // Log all incoming messages for debugging
    console.log("[CopilotKit Route] All incoming messages:");
    data?.messages?.forEach((msg: any, index: number) => {
      console.log(`  Message ${index}:`, {
        id: msg.id,
        role: msg.textMessage?.role || msg.role,
        contentLength: (msg.textMessage?.content || msg.content || "").length,
        contentPreview: (msg.textMessage?.content || msg.content || "").substring(0, 50) + "..."
      });
    });

    // Extract agent name from the request
    const agentName = data?.agentSession?.agentName || data?.metadata?.agent || "agenticChatAgent";
    const agent = agents[agentName as keyof typeof agents];
    
    if (!agent) {
      console.error(`[CopilotKit Route] Agent not found: ${agentName}`);
      return NextResponse.json({ error: "Agent not found" }, { status: 404 });
    }

    // Convert CopilotKit messages to AG-UI format
    const messages = data?.messages?.map((msg: any) => ({
      id: msg.id || `msg-${Date.now()}-${Math.random()}`,
      role: msg.textMessage?.role || msg.role || "user",
      content: msg.textMessage?.content || msg.content || "",
    }))
    .filter((msg: any) => {
      // Filter out empty content and CopilotKit system messages
      if (!msg.content) return false;
      if (msg.role === "system" && msg.content.includes("Please act as an efficient")) return false;
      return true;
    }) || [];

    // Create AG-UI input
    const agentInput = {
      messages,
      threadId: data?.threadId || data?.agentSession?.threadId || `thread-${Date.now()}`,
      runId: data?.runId || `run-${Date.now()}`,
      state: data?.agentStates?.[0]?.state || {},
      tools: [], // CopilotKit frontend tools would go here
      context: [],
      forwardedProps: data?.forwardedParameters || {},
    };

    console.log(`[CopilotKit Route] Calling AG-UI agent: ${agentName} with ${messages.length} messages`);
    console.log("[CopilotKit Route] Agent input:", JSON.stringify(agentInput, null, 2));

    // Create a streaming response
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        try {
          // Subscribe to the agent's observable response
          const observable = agent.run(agentInput);
          
          // Track stream closed state to avoid double close
          let isClosed = false;
          let eventCount = 0;

          const sendJSON = (data: any) => {
            if (isClosed) return;
            try {
              const jsonString = JSON.stringify(data);
              console.log(`[CopilotKit Route] Sending event ${++eventCount}:`, jsonString);
              // Use SSE format: "data: " prefix and double newline
              controller.enqueue(encoder.encode(`data: ${jsonString}\n\n`));
            } catch (e) {
              console.error("[CopilotKit Route] Error sending JSON:", e);
              // If controller is already closed, set flag
              isClosed = true;
            }
          };
          
          // First, send the GraphQL response header with initial empty messages
          const header = {
            data: {
              generateCopilotResponse: {
                threadId: agentInput.threadId,
                runId: agentInput.runId,
                messages: [], // Initialize with empty array
                __typename: "CopilotResponse"
              }
            }
          };
          sendJSON(header);

          // Don't send initial messages snapshot or agent state - go straight to streaming
          // This avoids potential conflicts with CopilotKit's internal message handling

          // If there are user messages, send them first
          if (messages.length > 0) {
            const userMessages = messages.filter((msg: any) => msg.role === "user");
            if (userMessages.length > 0) {
              const messagesSnapshot = {
                data: {
                  generateCopilotResponse: {
                    messages: userMessages.map((msg: any) => ({
                      __typename: "TextMessageOutput",
                      id: msg.id,
                      createdAt: new Date().toISOString(),
                      content: msg.content || "",
                      role: msg.role,
                      parentMessageId: null,
                      status: { code: "success", __typename: "SuccessMessageStatus" }
                    }))
                  }
                }
              };
              sendJSON(messagesSnapshot);
            }
          }

          // Track message content accumulation
          const messageContentMap = new Map<string, string>();
          let currentMessageId: string | null = null;

          // Then stream the AG-UI events as GraphQL messages
          observable.subscribe({
            next: (event: BaseEvent) => {
              console.log("[CopilotKit Route] Received AG-UI event:", {
                type: event.type,
                event: JSON.stringify(event)
              });

              // Convert AG-UI events to CopilotKit GraphQL format
              let graphqlEvent = null;

              if (event.type === EventType.TEXT_MESSAGE_START) {
                // Track the message ID for content accumulation
                const startEvent = event as any;
                currentMessageId = startEvent.messageId || `msg-${Date.now()}`;
                if (currentMessageId) {
                  messageContentMap.set(currentMessageId, "");
                }
                console.log(`[CopilotKit Route] TEXT_MESSAGE_START - messageId: ${currentMessageId}`);
              } else if (event.type === EventType.TEXT_MESSAGE_CONTENT) {
                // Cast to the specific event type to access its properties
                const textEvent = event as any; // AG-UI event types
                const messageId = textEvent.messageId || currentMessageId || `msg-${Date.now()}`;
                
                console.log("[CopilotKit Route] TEXT_MESSAGE_CONTENT event:", {
                  messageId,
                  delta: textEvent.delta,
                  content: textEvent.content,
                });
                
                // Initialize content string for this message if needed
                if (!messageContentMap.has(messageId)) {
                  messageContentMap.set(messageId, "");
                  console.log(`[CopilotKit Route] Initialized content for message ${messageId}`);
                }
                
                // Accumulate content as a string
                let currentContent = messageContentMap.get(messageId) ?? "";
                const previousLength = currentContent.length;
                
                if (textEvent.delta) {
                  currentContent += textEvent.delta;
                  console.log(`[CopilotKit Route] Added delta "${textEvent.delta}" to message ${messageId}`);
                } else if (textEvent.content) {
                  currentContent += textEvent.content;
                  console.log(`[CopilotKit Route] Added content "${textEvent.content}" to message ${messageId}`);
                }
                
                messageContentMap.set(messageId, currentContent);
                console.log(`[CopilotKit Route] Message ${messageId} content: "${currentContent}" (was ${previousLength} chars, now ${currentContent.length} chars)`);
                
                // Only send update every 10 characters or when we have a complete word/sentence
                const shouldSendUpdate = 
                  currentContent.length === 1 || // First character
                  currentContent.endsWith(' ') || // Word boundary
                  currentContent.endsWith('.') || // Sentence end
                  currentContent.endsWith('!') || // Sentence end
                  currentContent.endsWith('?') || // Sentence end
                  currentContent.endsWith('\n') || // Line break
                  (currentContent.length - previousLength) >= 10; // Every 10 chars
                
                if (shouldSendUpdate) {
                  graphqlEvent = {
                    data: {
                      generateCopilotResponse: {
                        messages: [{
                          __typename: "TextMessageOutput",
                          id: messageId,
                          createdAt: new Date().toISOString(),
                          content: currentContent, // Send as accumulated string
                          role: "assistant",
                          parentMessageId: messages.length > 0 ? messages[messages.length - 1].id : null,
                          status: { code: "success", __typename: "SuccessMessageStatus" }
                        }]
                      }
                    }
                  };
                }
              } else if (event.type === EventType.TEXT_MESSAGE_END) {
                console.log("[CopilotKit Route] TEXT_MESSAGE_END event received");
                // Send the final complete message
                const endEvent = event as any;
                const messageId = endEvent.messageId || currentMessageId;
                const finalContent = messageContentMap.get(messageId) || "";
                
                graphqlEvent = {
                  data: {
                    generateCopilotResponse: {
                      messages: [{
                        __typename: "TextMessageOutput",
                        id: messageId,
                        createdAt: new Date().toISOString(),
                        content: finalContent,
                        role: "assistant",
                        parentMessageId: messages.length > 0 ? messages[messages.length - 1].id : null,
                        status: { code: "success", __typename: "SuccessMessageStatus" }
                      }]
                    }
                  }
                };
              } else if (event.type === EventType.RUN_FINISHED) {
                console.log("[CopilotKit Route] RUN_FINISHED event received");
                graphqlEvent = {
                  data: {
                    generateCopilotResponse: {
                      status: { code: "success", __typename: "BaseResponseStatus" }
                    }
                  }
                };
              } else if (event.type === EventType.STATE_SNAPSHOT || event.type === EventType.STATE_DELTA) {
                console.log(`[CopilotKit Route] State event received: ${event.type}`);
                const stateEvent = event as any;
                
                // For state events, send an AgentStateMessageOutput
                graphqlEvent = {
                  data: {
                    generateCopilotResponse: {
                      messages: [{
                        __typename: "AgentStateMessageOutput",
                        id: `agent-state-${Date.now()}`,
                        createdAt: new Date().toISOString(),
                        threadId: agentInput.threadId,
                        state: event.type === EventType.STATE_SNAPSHOT ? stateEvent.snapshot : agentInput.state,
                        running: true,
                        agentName: agentName,
                        nodeName: "main",
                        runId: agentInput.runId,
                        active: true,
                        role: "assistant"
                      }]
                    }
                  }
                };
              } else {
                console.log(`[CopilotKit Route] Unhandled event type: ${event.type}`);
              }

              if (graphqlEvent) {
                sendJSON(graphqlEvent);
              }
            },
            error: (err) => {
              console.error("[CopilotKit Route] Agent error:", err);
              const errorEvent = {
                data: {
                  generateCopilotResponse: {
                    status: {
                      __typename: "FailedResponseStatus",
                      reason: "AGENT_ERROR",
                      details: { error: err.message }
                    }
                  }
                }
              };
              sendJSON(errorEvent);
              if (!isClosed) {
                controller.close();
                isClosed = true;
              }
            },
            complete: () => {
              console.log("[CopilotKit Route] Observable completed");
              if (!isClosed) {
                // Send SSE completion signal
                controller.enqueue(encoder.encode("data: [DONE]\n\n"));
                controller.close();
                isClosed = true;
              }
            }
          });
        } catch (error) {
          console.error("[CopilotKit Route] Error in stream start:", error);
          controller.error(error);
        }
      }
    });

    return new NextResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no", // Disable nginx buffering
      },
    });
  } catch (error) {
    console.error("[CopilotKit Route] Error:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
};
