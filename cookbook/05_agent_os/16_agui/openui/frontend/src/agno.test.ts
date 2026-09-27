import { EventType } from "@openuidev/react-ui";
import { describe, expect, it, vi } from "vitest";

import { agnoAGUIAdapter, createAgnoLLM } from "./agno";

function aguiResponse(events: object[]) {
  return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""), {
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("Agno AG-UI request", () => {
  it("includes Agno's required AG-UI extension containers", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 200 }));
    const llm = createAgnoLLM(fetchMock);

    await llm.send({
      threadId: "thread-1",
      messages: [{ id: "message-1", role: "user", content: "Hello" }],
      signal: new AbortController().signal,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, request] = fetchMock.mock.calls[0]!;
    const body = JSON.parse(request?.body as string);

    expect(body).toMatchObject({
      threadId: "thread-1",
      state: {},
      forwardedProps: {},
      tools: [],
      context: [],
    });
  });

  it("removes Agno's empty tool parent before a fast tool result", async () => {
    const adapter = agnoAGUIAdapter();
    const events = [
      { type: EventType.RUN_STARTED, threadId: "thread-1", runId: "run-1" },
      { type: EventType.STATE_SNAPSHOT, snapshot: {} },
      {
        type: EventType.TEXT_MESSAGE_START,
        messageId: "empty-parent",
        role: "assistant",
      },
      { type: EventType.RAW, event: { source: "agno" } },
      { type: EventType.TEXT_MESSAGE_END, messageId: "empty-parent" },
      {
        type: EventType.TOOL_CALL_START,
        toolCallId: "call-1",
        toolCallName: "get_quarterly_revenue",
        parentMessageId: "empty-parent",
      },
      { type: EventType.TOOL_CALL_ARGS, toolCallId: "call-1", delta: "{}" },
      { type: EventType.TOOL_CALL_END, toolCallId: "call-1" },
      {
        type: EventType.TOOL_CALL_RESULT,
        toolCallId: "call-1",
        messageId: "call-1",
        role: "tool",
        content: '{"quarters":[]}',
      },
      { type: EventType.TEXT_MESSAGE_START, messageId: "answer", role: "assistant" },
      { type: EventType.TEXT_MESSAGE_CONTENT, messageId: "answer", delta: "root = Card([])" },
      { type: EventType.TEXT_MESSAGE_END, messageId: "answer" },
      { type: EventType.RUN_FINISHED, threadId: "thread-1", runId: "run-1" },
    ];

    const parsed = [];
    for await (const event of adapter.parse(aguiResponse(events))) parsed.push(event);

    expect(parsed.map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_START,
      EventType.TOOL_CALL_ARGS,
      EventType.TOOL_CALL_END,
      EventType.TOOL_CALL_RESULT,
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.TEXT_MESSAGE_END,
    ]);
  });
});
