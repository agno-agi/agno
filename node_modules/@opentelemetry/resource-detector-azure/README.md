# OpenTelemetry Resource Detector for Azure

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

[component owners](https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/.github/component_owners.yml): @JacksonWeber

Resource detector for Azure.

## Installation

```bash
npm install --save @opentelemetry/resource-detector-azure
```

## Usage

```typescript
import { detectResources } from '@opentelemetry/resources';
import { azureAppServiceDetector } from '@opentelemetry/resource-detector-azure';
const resource = detectResources({
    detectors: [azureAppServiceDetector],
});

const tracerProvider = new NodeTracerProvider({ resource });
```

## Available Detectors

This package implements Semantic Convention [Version 1.19.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.19.0/semantic_conventions/README.md).

### App Service Resource Detector

| Resource Attribute      | Description                                                                                                                                                                                               |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| azure.app.service.stamp | The specific "stamp" cluster within Azure where the App Service is running, e.g., "waws-prod-sn1-001". Value of Process Environment Variable `APP_SERVICE_ATTRIBUTE_ENV_VARS`.                            |
| cloud.platform          | The cloud platform. Here, it's always "azure_app_service".                                                                                                                                                |
| cloud.provider          | The cloud service provider. In this context, it's always "azure".                                                                                                                                         |
| cloud.region            | The Azure region where the App Service is hosted, e.g., "East US", "West Europe", etc.  Value of Process Environment Variable `REGION_NAME`.                                                              |
| cloud.resource_id       | The Azure Resource Manager URI uniquely identifying the Azure App Service. Typically in the format `/subscriptions/{subscriptionId}/resourceGroups/{groupName}/providers/Microsoft.Web/sites/{siteName}`. |
| deployment.environment  | The deployment slot where the Azure App Service is running, such as "staging", "production", etc. Value of Process Environment Variable `WEBSITE_SLOT_NAME`.                                              |
| host.id                 | The primary hostname for the app, excluding any custom hostnames. Value of Process Environment Variable `WEBSITE_HOSTNAME`.                                                                               |
| service.instance.id     | The specific instance of the Azure App Service, useful in a scaled-out configuration. Value of Process Environment Variable `WEBSITE_INSTANCE_ID`.                                                        |
| service.name            | The name of the Azure App Service. Value of Process Environment Variable `WEBSITE_SITE_NAME`.                                                                                                             |

### VM Resource Detector

| Resource Attribute       | Description                                                                                                                                                                                              |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| azure.vm.scaleset.name   | The name of the Virtual Machine Scale Set if the VM is part of one. Value from `vmScaleSetName` key on `/metadata/instance/compute` request.                                                             |
| azure.vm.sku             | The SKU of the Azure Virtual Machine's operating system. For instance, for a VM running Windows Server 2019 Datacenter edition, this value would be "2019-Datacenter". Value from `sku` key on `/metadata/instance/compute` request. |
| cloud.platform           | The cloud platform, which is always set to "azure_vm" in this context.                                                                                                                                   |
| cloud.provider           | The cloud service provider, which is always set to "azure" in this context.                                                                                                                              |
| cloud.region             | The Azure region where the Virtual Machine is hosted, such as "East US", "West Europe", etc. Value from `location` key on `/metadata/instance/compute` request.                                          |
| cloud.resource_id        | The Azure Resource Manager URI uniquely identifying the Azure Virtual Machine. It typically follows this format: `/subscriptions/{subscriptionId}/resourceGroups/{groupName}/providers/Microsoft.Compute/virtualMachines/{vmName}`. Value from `resourceId` key on `/metadata/instance/compute` request.|
| host.id                  | A unique identifier for the VM host, for instance, "02aab8a4-74ef-476e-8182-f6d2ba4166a6". Value from `vmId` key on `/metadata/instance/compute` request.                                                |
| host.name                | The name of the host machine. Value from `name` key on `/metadata/instance/compute` request.                                                                                                             |
| host.type                | The size of the VM instance, for example, "Standard_D2s_v3". Value from `vmSize` key on `/metadata/instance/compute` request.                                                                            |
| os.version               | The version of the operating system running on the VM. Value from `version` key on `/metadata/instance/compute` request.                                                                                 |

### Azure Functions Resource Detector

| Resource Attribute      | Description                                                                                                                                          |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| cloud.platform          | The cloud platform. Here, it's always "azure_functions".                                                                                             |
| cloud.provider          | The cloud service provider. In this context, it's always "azure".                                                                                    |
| cloud.region            | The Azure region where the Azure Function is hosted, e.g., "East US", "West Europe", etc. Value of Process Environment Variable `REGION_NAME`.       |
| faas.instance           | The specific instance of the Azure App Service, useful in a scaled-out configuration. Value from Process Environment Variable `WEBSITE_INSTANCE_ID`. |
| faas.max_memory         | The amount of memory available to the Azure Function expressed in MiB. value from Process Environment Variable `WEBSITE_MEMORY_LIMIT_MB`.            |
| service.name            | The name of the service the Azure Functions runs within. Value from Process Environment Variable `WEBSITE_SITE_NAME`.                                |
| cloud.resource_id       | The Azure Resource Manager URI uniquely identifying the Azure Virtual Machine. It typically follows this format: /subscriptions/{subscriptionId}/resourceGroups/{groupName}/providers/Microsoft.Compute/virtualMachines/{vmName}. Value from resourceId key on /metadata/instance/compute request. |
| process.pid             | The process ID collected from the running process.                                                                                                   |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/resource-detector-azure
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Fresource-detector-azure.svg
