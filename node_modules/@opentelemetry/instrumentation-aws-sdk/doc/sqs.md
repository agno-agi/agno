# SQS

SQS is Amazon's managed message queue. Thus, it should follow the [OpenTelemetry specification for Messaging systems](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/).

## Specific trace semantic

The following methods are automatically enhanced:

### sendMessage / sendMessageBatch

- [Messaging Attributes](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/#messaging-attributes) are added by this instrumentation according to the spec.
- OpenTelemetry trace context is injected as SQS MessageAttributes, so the service receiving the message can link cascading spans to the trace which created the message.

### receiveMessage

- [Messaging Attributes](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/#messaging-attributes) are added by this instrumentation according to the spec.
- Sets the inter process context correctly, so that additional spans created through the process will be linked to parent spans correctly.
  When multiple messages are received, the instrumentation will attach spank links to the receiving span containing the trace context and message ID of each message.
- Extract trace context from SQS MessageAttributes, and set span's `parent` and `links` correctly according to the spec.
