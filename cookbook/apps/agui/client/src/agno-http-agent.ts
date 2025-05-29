const BACKEND_URL = process.env.NEXT_PUBLIC_AGNO_BACKEND_URL || "http://localhost:8000";

export class AgnoHttpAgent {
  private agentName: string;
  private url: string;
  private headers: Record<string, string>;

  constructor({ agentName }: { agentName: string }) {
    this.agentName = agentName;
    this.url = `${BACKEND_URL}/agui/awp?agent=${agentName}`;
    this.headers = {
      "Content-Type": "application/json",
    };
    console.log(`[AgnoHttpAgent] Creating agent: ${agentName} -> URL: ${this.url}`);
  }

  run(input: any) {
    // Return an Observable-like object for compatibility with the AG-UI route
    return {
      subscribe: (observer: {
        next: (event: any) => void;
        error: (err: any) => void;
        complete: () => void;
      }) => {
        this.runStream(input, observer);
      }
    };
  }

  private async runStream(input: any, observer: {
    next: (event: any) => void;
    error: (err: any) => void;
    complete: () => void;
  }) {
    console.log(`[AgnoHttpAgent] Running agent ${this.agentName} with input:`, {
      messages: input.messages,
      threadId: input.threadId,
      runId: input.runId,
    });

    try {
      const response = await fetch(this.url, {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify({
          messages: input.messages.map((msg: any) => ({
            id: msg.id,
            role: msg.role,
            content: msg.content,
          })),
          thread_id: input.threadId,
          run_id: input.runId || `run-${Date.now()}`,
          state: input.state || {},
          tools: input.tools || [],
          context: input.context || [],
          forwarded_props: input.forwardedProps || {},
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (!reader) {
        throw new Error("No response body");
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.trim() === "") continue;

          // Parse SSE format
          if (line.startsWith("data: ")) {
            const eventData = line.substring(6);
            try {
              const event = JSON.parse(eventData);
              console.log(`[AgnoHttpAgent] Event: ${event.type}`);
              
              // Pass through AG-UI events directly
              observer.next(event);
            } catch (e) {
              console.error("[AgnoHttpAgent] Error parsing event:", e, eventData);
            }
          }
        }
      }

      console.log("[AgnoHttpAgent] Stream completed");
      observer.complete();
    } catch (error) {
      console.error("[AgnoHttpAgent] Error:", error);
      observer.error(error);
    }
  }
}

// Factory function to create agents
export function createAgnoAgent(agentName: string) {
  return new AgnoHttpAgent({ agentName });
} 