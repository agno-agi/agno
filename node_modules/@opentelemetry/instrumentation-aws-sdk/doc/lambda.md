# Lambda

Lambda is Amazon's function-as-a-service (FaaS) platform. This instrumentation follows the [OpenTelemetry specification for FaaS systems](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/trace/semantic_conventions/faas.md).

## Specific trace semantics

The following methods are automatically enhanced:

### Invoke

- Attributes are added by this instrumentation according to the [spec for Outgoing Invocations of a FaaS from a client](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/trace/semantic_conventions/faas.md#outgoing-invocations) .
- OpenTelemetry trace context is injected into the `ClientContext` parameter, allowing functions to extract this using the `custom` property within the function.
