import {
  HttpAgent,
  RunAgentInput,
  EventType,
  BaseEvent,
} from "@ag-ui/client";
import { Observable } from "rxjs";
import { tap } from "rxjs/operators";

/**
 * HTTP Agent that connects to Agno backend via AG-UI protocol
 */
export class AgnoHttpAgent extends HttpAgent {
  private agentName: string;
  
  constructor(
    agentName: string = "default",
    private baseUrl: string = process.env.NEXT_PUBLIC_AGNO_URL || "http://localhost:8000"
  ) {
    // Store agent name for logging
    const storedAgentName = agentName;
    
    // Construct the AG-UI endpoint URL
    const agentUrl = `${baseUrl}/agui/awp?agent=${agentName}`;
    
    console.log(`[AgnoHttpAgent] Creating agent: ${agentName} -> URL: ${agentUrl}`);
    
    super({
      url: agentUrl,
      headers: {
        "Content-Type": "application/json",
      },
    });
    
    this.agentName = storedAgentName;
  }

  /**
   * Override run method to add any custom behavior if needed
   */
  run(input: RunAgentInput): Observable<BaseEvent> {
    // The HttpAgent base class handles the AG-UI protocol communication
    // We can add custom logging or error handling here if needed
    console.log(`[AgnoHttpAgent] Running agent ${this.agentName} with input:`, {
      messages: input.messages?.map(m => ({ role: m.role, content: m.content })),
      state: input.state,
      threadId: input.threadId,
      runId: input.runId,
    });
    
    // Log the actual URL being called
    console.log(`[AgnoHttpAgent] Calling URL: ${this.baseUrl}/agui/awp?agent=${this.agentName}`);
    
    // Call parent run method and add logging
    return super.run(input).pipe(
      tap({
        next: (event: BaseEvent) => {
          console.log(`[AgnoHttpAgent] Received event:`, {
            type: event.type,
            event: JSON.stringify(event),
            timestamp: new Date().toISOString()
          });
          
          // Log specific event details
          if (event.type === EventType.TEXT_MESSAGE_CONTENT) {
            const textEvent = event as any;
            console.log(`[AgnoHttpAgent] TEXT_MESSAGE_CONTENT details:`, {
              messageId: textEvent.messageId,
              delta: textEvent.delta,
              content: textEvent.content,
            });
          }
        },
        error: (err) => {
          console.error(`[AgnoHttpAgent] Error:`, err);
        },
        complete: () => {
          console.log(`[AgnoHttpAgent] Stream completed`);
        }
      })
    );
  }
}

/**
 * Agent name mapping for Dojo features
 */
const AGENT_MAPPING = {
  // Map CopilotKit agent names to Agno backend agent names
  agenticChatAgent: "chat_agent",
  agentiveGenerativeUIAgent: "generative_ui_agent", 
  humanInTheLoopAgent: "human_in_loop_agent",
  predictiveStateUpdatesAgent: "predictive_state_agent",
  sharedStateAgent: "shared_state_agent",
  toolBasedGenerativeUIAgent: "tool_ui_agent",
} as const;

/**
 * Factory function to create Agno HTTP agents with proper naming
 */
export function createAgnoAgent(copilotAgentName: keyof typeof AGENT_MAPPING): AgnoHttpAgent {
  const agnoAgentName = AGENT_MAPPING[copilotAgentName];
  
  console.log(`[createAgnoAgent] Mapping ${copilotAgentName} -> ${agnoAgentName}`);
  
  if (!agnoAgentName) {
    console.warn(`No mapping found for agent: ${copilotAgentName}, using default`);
    return new AgnoHttpAgent("chat_agent");
  }
  
  return new AgnoHttpAgent(agnoAgentName);
} 