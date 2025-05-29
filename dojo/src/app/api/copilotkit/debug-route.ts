import { NextRequest, NextResponse } from "next/server";

export const POST = async (req: NextRequest) => {
  console.log("[Debug Route] Request received");
  
  const body = await req.json();
  console.log("[Debug Route] Request body:", JSON.stringify(body, null, 2));
  
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const sendEvent = (data: any) => {
        const jsonString = JSON.stringify(data);
        controller.enqueue(encoder.encode(`data: ${jsonString}\n\n`));
      };
      
      // Send header
      sendEvent({
        data: {
          generateCopilotResponse: {
            threadId: "debug-thread",
            runId: "debug-run",
            __typename: "CopilotResponse"
          }
        }
      });
      
      // Wait a bit
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Send the full message at once
      sendEvent({
        data: {
          generateCopilotResponse: {
            messages: [{
              __typename: "TextMessageOutput",
              id: "debug-msg-1",
              createdAt: new Date().toISOString(),
              content: "This is a debug response from the debug route!",
              role: "assistant",
              status: { code: "success", __typename: "SuccessMessageStatus" }
            }]
          }
        }
      });
      
      // Wait a bit
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Send completion
      sendEvent({
        data: {
          generateCopilotResponse: {
            status: { code: "success", __typename: "BaseResponseStatus" }
          }
        }
      });
      
      // End stream
      controller.enqueue(encoder.encode("data: [DONE]\n\n"));
      controller.close();
    }
  });
  
  return new NextResponse(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}; 