# OpenTelemetry Net module Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the [`net`](http://nodejs.org/dist/latest/docs/api/net.html) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

Supports both TCP and IPC connections.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-net
```

## Supported Versions

- Node.js `>=14`

## Usage

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { NetInstrumentation } = require('@opentelemetry/instrumentation-net');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new NetInstrumentation(),
    // other instrumentations
  ],
});
```

## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes added to `connect` spans:

| Attribute                 | Short Description                                                        |
|---------------------------|--------------------------------------------------------------------------|
| `net.transport`           | `IP.TCP`, `pipe` or `Unix`                                               |
| `net.peer.name`           | Host name or the IPC file path                                           |
| `net.peer.ip` (for TCP)   | Remote address of the peer (dotted decimal for IPv4 or RFC5952 for IPv6) |
| `net.peer.port` (for TCP) | Remote port number                                                       |
| `net.host.ip` (for TCP)   | Like net.peer.ip but for the host IP. Useful in case of a multi-IP host  |
| `net.host.port` (for TCP) | Like net.peer.port but for the host port                                 |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-net
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-net.svg
