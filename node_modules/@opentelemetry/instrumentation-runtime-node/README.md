# OpenTelemetry Node.js Runtime Metrics Instrumentation

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic metric instrumentation that exposes measurements from the [Performance measurement APIs](https://nodejs.org/api/perf_hooks.html) (i.e. `perf_hooks`).
While currently it is limited to metrics, it may be modified to produce other signals in the future.

## Supported Versions

- Node.js `>=14.10`

<!-- - 14.6.0 - this package uses _private properties_ -->

## Example

```bash
npm install --save @opentelemetry/sdk-node @opentelemetry/exporter-prometheus
npm install --save @opentelemetry/instrumentation-runtime-node
```

```js
import { NodeSDK } from '@opentelemetry/sdk-node';
import { PrometheusExporter } from '@opentelemetry/exporter-prometheus';
import { RuntimeNodeInstrumentation } from '@opentelemetry/instrumentation-runtime-node';

const prometheusExporter = new PrometheusExporter({
  port: 9464,
  startServer: true
});

const sdk = new NodeSDK({
  metricReader: prometheusExporter,
  instrumentations: [new RuntimeNodeInstrumentation({
    monitoringPrecision: 5000,
  })],
});

sdk.start()
```

[`NodeSDK`](https://www.npmjs.com/package/@opentelemetry/sdk-node) is the full OpenTelemetry SDK for Node.js that is a layer of abstraction on top of the `@opentelemetry/sdk-metrics` and `@opentelemetry/sdk-trace-*` packages. By specifying `metricReader`, it will initialize the metrics SDK and creates a `MeterProvider`. [`@opentelemetry/exporter-prometheus`](https://www.npmjs.com/package/@opentelemetry/exporter-prometheus) will output metrics collected by registered instrumentation on a `/metrics` endpoint.

Go to [`localhost:9464/metrics`](http://localhost:9464/metrics), and you should see:

```txt
# HELP nodejs_performance_event_loop_utilization Event loop utilization
# UNIT nodejs_performance_event_loop_utilization 1
# TYPE nodejs_performance_event_loop_utilization gauge
nodejs_performance_event_loop_utilization 0.010140079547955264
```

> Metrics will only be exported after it has collected two ELU readings (at least approximately `RuntimeNodeInstrumentationConfig.monitoringPrecision` milliseconds after initialization). Otherwise, you may see:
>
> ```txt
> # no registered metrics
> ```

### Options

`RuntimeNodeInstrumentation`'s constructor accepts the following options:

| name | type | unit | default | description |
|---|---|---|---------|---|
| [`monitoringPrecision`](./src/types.ts#L25) | `int` | millisecond | `10`    | The approximate number of milliseconds for which to calculate event loop utilization averages. A larger value will result in more accurate averages at the expense of less granular data. Should be set to below the scrape interval of your metrics collector to avoid duplicated data points. |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-runtime-node
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-runtime-node.svg
