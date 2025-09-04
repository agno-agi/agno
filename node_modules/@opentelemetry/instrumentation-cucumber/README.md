# OpenTelemetry Cucumber Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the [`@cucumber/cucumber`](https://www.npmjs.com/package/@cucumber/cucumber) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-cucumber
```

## Supported Versions

- [`@cucumber/cucumber`](https://www.npmjs.com/package/@cucumber/cucumber) versions `>=8.0.0 <11`

## Usage

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const {
  CucumberInstrumentation,
} = require('@opentelemetry/instrumentation-cucumber');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new CucucmberInstrumentation({
      // see below for available configuration
    }),
  ],
});
```

### Cucumber Instrumentation Options

Cucumber instrumentation has currently no options.

| Options | Type | Description |
| ------- | ---- | ----------- |

## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute            | Short Description                                                                |
| -------------------- | -------------------------------------------------------------------------------- |
| `code.file.path`     | The source code file name that identifies the code unit as uniquely as possible. |
| `code.function.name` | The method or function fully-qualified name without arguments.                   |
| `code.line.number`   | The line number in `code.file.path` best representing the operation.             |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-cucumber
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-cucumber.svg
