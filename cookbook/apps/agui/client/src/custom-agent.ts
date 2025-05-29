import {
  AbstractAgent,
  RunAgentInput,
  EventType,
  BaseEvent,
} from "@ag-ui/client";
import { Observable } from "rxjs";

export class CustomAgent extends AbstractAgent {
  protected run(input: RunAgentInput): Observable<BaseEvent> {
    const messageId = Date.now().toString();
    return new Observable<BaseEvent>((observer) => {
      observer.next({
        type: EventType.RUN_STARTED,
        threadId: input.threadId,
        runId: input.runId,
      } as any);

      observer.next({
        type: EventType.TEXT_MESSAGE_START,
        messageId,
      } as any);

      observer.next({
        type: EventType.TEXT_MESSAGE_CONTENT,
        messageId,
        delta: "Hello world!",
      } as any);

      observer.next({
        type: EventType.TEXT_MESSAGE_END,
        messageId,
      } as any);

      observer.next({
        type: EventType.RUN_FINISHED,
        threadId: input.threadId,
        runId: input.runId,
      } as any);

      observer.complete();
    });
  }
}
