# OpenTelemetry gRPC Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

**Note: This is an experimental package under active development. New releases may include breaking changes.**

This module provides automatic instrumentation for [`@grpc/grpc-js`](https://grpc.io/blog/grpc-js-1.0/). Currently, version [`1.x`](https://www.npmjs.com/package/@grpc/grpc-js?activeTab=versions) of `@grpc/grpc-js` is supported.

For automatic instrumentation see the
[@opentelemetry/sdk-trace-node](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package.

## Installation

```sh
npm install --save @opentelemetry/instrumentation-grpc
```

## Supported Versions

- [`@grpc/grpc-js`](https://www.npmjs.com/package/@grpc/grpc-js) versions `^1.0.0`

## Usage

OpenTelemetry gRPC Instrumentation allows the user to automatically collect trace data and export them to the backend of choice, to give observability to distributed systems when working with ([grpc-js](https://www.npmjs.com/package/@grpc/grpc-js)).

To load a specific instrumentation (**gRPC** in this case), specify it in the Node Tracer's configuration.

```javascript
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { GrpcInstrumentation } = require('@opentelemetry/instrumentation-grpc');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider({
  spanProcessors: [new SimpleSpanProcessor(new ConsoleSpanExporter())]
});

provider.register();

registerInstrumentations({
  instrumentations: [new GrpcInstrumentation()]
});

```

See [examples/grpc-js](https://github.com/open-telemetry/opentelemetry-js/tree/main/examples/grpc-js) for examples.

### gRPC Instrumentation Options

gRPC instrumentation accepts the following configuration:

| Options                                                                                                                                                              | Type              | Description                                                                                                                                                                                                                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`ignoreGrpcMethods`](https://github.com/open-telemetry/opentelemetry-js/blob/main/experimental/packages/opentelemetry-instrumentation-grpc/src/types.ts#L25)        | `IgnoreMatcher[]` | gRPC instrumentation will not trace any methods that match anything in this list. You may pass a string (case-insensitive match), a `RegExp` object, or a filter function.                                                                                                           |
| [`metadataToSpanAttributes`](https://github.com/open-telemetry/opentelemetry-js/blob/main/experimental/packages/opentelemetry-instrumentation-grpc/src/types.ts#L27) | `object`          | List of case insensitive metadata to convert to span attributes. Client and server (outgoing requests, incoming responses) metadata attributes will be converted to span attributes in the form of `rpc.{request\response}.metadata.metadata_key`, e.g. `rpc.response.metadata.date` |

## Semantic Conventions

Up to and including v0.200.0, `instrumentation-grpc` generates telemetry using [Semantic Conventions v1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md).

HTTP semantic conventions (semconv) were stabilized in v1.23.0, and a [migration process](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/non-normative/http-migration.md#http-semantic-convention-stability-migration) was defined.
`instrumentation-grpc` versions 0.201.0 and later include support for migrating to stable HTTP semantic conventions, as described below.
The intent is to provide an approximate 6 month time window for users of this instrumentation to migrate to the new HTTP semconv, after which a new minor version will use the *new* semconv by default and drop support for the old semconv.
See the [HTTP semconv migration plan for OpenTelemetry JS instrumentations](https://github.com/open-telemetry/opentelemetry-js/issues/5646).

To select which semconv version(s) is emitted from this instrumentation, use the `OTEL_SEMCONV_STABILITY_OPT_IN` environment variable.

- `http`: emit the new (stable) v1.23.0 semantics
- `http/dup`: emit **both** the old v1.7.0 and the new (stable) v1.23.0 semantics
- By default, if `OTEL_SEMCONV_STABILITY_OPT_IN` includes neither of the above tokens, the old v1.7.0 semconv is used.

### Attributes collected

| v1.7.0 semconv  | v1.23.0 semconv  | Short Description                                          |
| --------------- | ---------------- | ---------------------------------------------------------- |
| `net.peer.name` | `server.address` | Server domain name if available without reverse DNS lookup |
| `net.peer.port` | `server.port`    | Server port number                                         |

| Attribute     | Short Description                                                                                  |
| ------------- | -------------------------------------------------------------------------------------------------- |
| `rpc.method`  | The name of the (logical) method being called, must be equal to the $method part in the span name. |
| `rpc.service` | The full (logical) name of the service being called, including its package name, if applicable.    |
| `rpc.system`  | A string identifying the remoting system.                                                          |

### Upgrading Semantic Conventions

When upgrading to the new semantic conventions, it is recommended to do so in the following order:

1. Upgrade `@opentelemetry/instrumentation-grpc` to the latest version
2. Set `OTEL_SEMCONV_STABILITY_OPT_IN=http/dup` to emit both old and new semantic conventions
3. Modify alerts, dashboards, metrics, and other processes to expect the new semantic conventions
4. Set `OTEL_SEMCONV_STABILITY_OPT_IN=http` to emit only the new semantic conventions

This will cause both the old and new semantic conventions to be emitted during the transition period.

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-grpc
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-grpc.svg
