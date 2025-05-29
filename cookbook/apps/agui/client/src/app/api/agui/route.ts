import { createAgnoAgent } from "../../../agno-http-agent";
import { NextRequest, NextResponse } from "next/server";
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
    
    // Extract agent name from request
    const agentName = body.agent || "agenticChatAgent";
    const agent = agents[agentName as keyof typeof agents];
    
    if (!agent) {
      return NextResponse.json({ error: "Agent not found" }, { status: 404 });
    }

    // Create AG-UI input from the request
    const agentInput = {
      messages: body.messages || [],
      threadId: body.threadId || `thread-${Date.now()}`,
      runId: body.runId || `run-${Date.now()}`,
      state: body.state || {},
      tools: body.tools || [],
      context: body.context || [],
      forwardedProps: body.forwardedProps || {},
    };

    console.log(`[AG-UI Route] Running agent: ${agentName}`);

    // Create SSE stream
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        try {
          // Subscribe to the agent's observable response
          const observable = agent.run(agentInput);
          
          observable.subscribe({
            next: (event: BaseEvent) => {
              // Send event as SSE
              const sseEvent = `data: ${JSON.stringify(event)}\n\n`;
              controller.enqueue(encoder.encode(sseEvent));
            },
            error: (err: any) => {
              console.error("[AG-UI Route] Agent error:", err);
              const errorEvent = {
                type: EventType.RUN_ERROR,
                message: err.message || "Unknown error",
              };
              const sseEvent = `data: ${JSON.stringify(errorEvent)}\n\n`;
              controller.enqueue(encoder.encode(sseEvent));
              controller.close();
            },
            complete: () => {
              controller.close();
            }
          });
        } catch (error) {
          console.error("[AG-UI Route] Error:", error);
          controller.error(error);
        }
      }
    });

    return new NextResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  } catch (error) {
    console.error("[AG-UI Route] Error:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}; 