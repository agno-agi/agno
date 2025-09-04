# OpenTelemetry DNS Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the [`dns`](http://nodejs.org/dist/latest/docs/api/dns.html) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Status

| Maturity                                              | [Component Owner](../../.github/component_owners.yml) | Compatibility         |
| ----------------------------------------------------- | -------------------------------------------------------- | --------------------- |
| [Unmaintained](../../CONTRIBUTING.md#unmaintained) | N/A                                                      | API 1.0+<br/>SDK 1.0+ |

## Installation

```bash
npm install --save @opentelemetry/instrumentation-dns
```

## Supported Versions

- Node.js `>=14`

## Usage

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { DnsInstrumentation } = require('@opentelemetry/instrumentation-dns');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new DnsInstrumentation({
      // see under for available configuration
    }),
  ],
});
```

### DNS Instrumentation Options

DNS instrumentation has currently one option. You can set the following:

| Options | Type | Description |
| ------- | ---- | ----------- |
| [`ignoreHostnames`](https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/packages/instrumentation-dns/src/types.ts#L99) | `IgnoreMatcher \| IgnoreMatcher[]` | DNS instrumentation will not trace all requests that match hostnames |

## Semantic Conventions

This package does not currently generate any attributes from semantic conventions.

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-dns
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-dns.svg
