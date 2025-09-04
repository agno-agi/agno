# OpenTelemetry Resource Detector for GCP

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

Resource detector for Google Cloud Platform.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

The GCP resource detector requires Node.JS 10+ due to a dependency on [`gcp-metadata`][] which uses features only available in Node.JS 10+.

```bash
npm install --save @opentelemetry/resource-detector-gcp
```

## Usage

```typescript
import { detectResources } from '@opentelemetry/resources';
import { gcpDetector } from '@opentelemetry/resource-detector-gcp'
const resource = await detectResources({
   detectors: [gcpDetector],
})

const tracerProvider = new NodeTracerProvider({ resource });
```

## Available detectors

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

### GCP Detector

| Resource Attribute      | Description                                                   |
|-------------------------|---------------------------------------------------------------|
| cloud.account.id        | Value of `project-id` from GCP Metadata project               |
| cloud.availability_zone | Value of `zone` from GCP Metadata instance                    |
| cloud.provider          | The cloud provider. In this context, it's always "gcp"        |
| container.name          | Value of Environment Variable `CONTAINER_NAME`                |
| host.id                 | Value of `id` from GCP Metadata instance                      |
| host.name               | Value of `hostname` from GCP Metadata instance                |
| k8s.cluster.name        | Value of `attributes/cluster-name` from GCP Metadata instance |
| k8s.namespace.name      | Value of Environment Variable `NAMESPACE`                     |
| k8s.pod.name            | Value of Environment Variable `HOSTNAME`                      |

## Useful links

- [GCP Metadata Documentation][]
- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[`gcp-metadata`]: https://www.npmjs.com/package/gcp-metadata
[GCP Metadata Documentation]: https://cloud.google.com/compute/docs/metadata/overview
[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/resource-detector-gcp
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Fresource-detector-gcp.svg
