# SNS

SNS is amazon's managed pub/sub system. Thus, it should follow the [OpenTelemetry specification for Messaging systems](https://github.com/open-telemetry/opentelemetry-specification/blob/master/specification/trace/semantic_conventions/messaging.md).

## Specific trace semantic

The following methods are automatically enhanced:

### Publish messages

- [Messaging Attributes](https://github.com/open-telemetry/opentelemetry-specification/blob/master/specification/trace/semantic_conventions/messaging.md#messaging-attributes) are added by this instrumentation according to the spec.
- OpenTelemetry trace context is injected as SNS MessageAttributes, so the service receiving the message can link cascading spans to the trace which created the message.

### Consumers

There are many potential consumers: SQS, Lambda, HTTP/S, Email, SMS, mobile notifications. each one of them will received the propagated context in its own way.

## Integration with SQS

AWS provide two ways of integrating SNS and SQS, one sends the message "as is" and one being parsed, this is called raw message delivery.

When it is turn off (by default) message attributes (sent in SNS) will appear in the payload of SQS, if it turned on the payload will be parsed before sent to SQS and the SNS attributes will be mapped to SQS Message attribute which allow this instrumentation to have propagated context works out-of-the-box.

If raw message delivery is turned off, you can solve it by enabling `sqsExtractContextPropagationFromPayload`, it will extract the context from the payload. It does have some performance affect as the instrumentation will run `JSON.parse` to get the data.

More details about raw message deliver can be found in [AWS docs](https://docs.aws.amazon.com/sns/latest/dg/sns-large-payload-raw-message-delivery.html)

>If you see partial / broken traces when integrating SNS with SQS this might be the reason
