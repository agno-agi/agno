import {
  type AGUIEvent,
  agUIAdapter,
  EventType,
  fetchLLM,
  type StreamProtocolAdapter,
} from "@openuidev/react-ui";

const OPENUI_CHAT_EVENT_TYPES = new Set<AGUIEvent["type"]>([
  EventType.TEXT_MESSAGE_START,
  EventType.TEXT_MESSAGE_CHUNK,
  EventType.TEXT_MESSAGE_CONTENT,
  EventType.TEXT_MESSAGE_END,
  EventType.TOOL_CALL_START,
  EventType.TOOL_CALL_CHUNK,
  EventType.TOOL_CALL_ARGS,
  EventType.TOOL_CALL_END,
  EventType.TOOL_CALL_RESULT,
  EventType.RUN_ERROR,
]);

/**
 * Normalize Agno's AG-UI stream for OpenUI's chat message processor.
 *
 * Agno emits run/state events plus an empty assistant message as the parent of
 * a backend tool call. OpenUI 0.13.6 materializes those ignored events as an
 * empty message and debounces the following tool-call update. A fast tool
 * result can then render as an orphan activity and leave ToolCallTimeline with
 * no display step. Only forward events consumed by the chat processor and
 * suppress empty text-message envelopes so the tool call is stored first.
 */
export function agnoAGUIAdapter(): StreamProtocolAdapter {
  const adapter = agUIAdapter();

  return {
    async *parse(response) {
      let pendingTextStart: AGUIEvent | undefined;
      let pendingTextEvents: AGUIEvent[] = [];

      for await (const event of adapter.parse(response)) {
        if (!OPENUI_CHAT_EVENT_TYPES.has(event.type)) continue;

        if (event.type === EventType.TEXT_MESSAGE_START) {
          if (pendingTextStart) {
            yield pendingTextStart;
            yield* pendingTextEvents;
          }
          pendingTextStart = event;
          pendingTextEvents = [];
          continue;
        }

        if (pendingTextStart) {
          if (
            event.type === EventType.TEXT_MESSAGE_CHUNK ||
            event.type === EventType.TEXT_MESSAGE_CONTENT
          ) {
            yield pendingTextStart;
            yield* pendingTextEvents;
            pendingTextStart = undefined;
            pendingTextEvents = [];
            yield event;
            continue;
          }

          if (event.type === EventType.TEXT_MESSAGE_END) {
            pendingTextStart = undefined;
            pendingTextEvents = [];
            continue;
          }

          pendingTextEvents.push(event);
          continue;
        }

        yield event;
      }

      if (pendingTextStart) {
        yield pendingTextStart;
        yield* pendingTextEvents;
      }
    },
  };
}

export function createAgnoLLM(fetchImpl?: typeof fetch) {
  return fetchLLM({
    url: "/agui",
    streamAdapter: agnoAGUIAdapter(),
    // Agno's RunAgentInput model requires the two optional AG-UI extension
    // containers to be present, even when this example does not use them.
    body: { state: {}, forwardedProps: {} },
    fetch: fetchImpl,
  });
}
