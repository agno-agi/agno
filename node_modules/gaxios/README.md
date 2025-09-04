# gaxios

[![npm version](https://img.shields.io/npm/v/gaxios.svg)](https://www.npmjs.org/package/gaxios)
[![codecov](https://codecov.io/gh/googleapis/gaxios/branch/master/graph/badge.svg)](https://codecov.io/gh/googleapis/gaxios)
[![Code Style: Google](https://img.shields.io/badge/code%20style-google-blueviolet.svg)](https://github.com/google/gts)

> An HTTP request client that provides an `axios` like interface over top of `node-fetch`.

## Install

```sh
$ npm install gaxios
```

## Example

```js
const {request} = require('gaxios');
const res = await request({
  url: 'https://www.googleapis.com/discovery/v1/apis/',
});
```

## Setting Defaults

Gaxios supports setting default properties both on the default instance, and on additional instances. This is often useful when making many requests to the same domain with the same base settings. For example:

```js
const gaxios = require('gaxios');
gaxios.instance.defaults = {
  baseURL: 'https://example.com'
  headers: {
    Authorization: 'SOME_TOKEN'
  }
}
gaxios.request({url: '/data'}).then(...);
```

Note that setting default values will take precedence
over other authentication methods, i.e., application default credentials.

## Request Options

```ts
interface GaxiosOptions = {
  // The url to which the request should be sent.  Required.
  url: string,

  // The HTTP method to use for the request.  Defaults to `GET`.
  method: 'GET',

  // The base Url to use for the request. Prepended to the `url` property above.
  baseURL: 'https://example.com';

  // The HTTP methods to be sent with the request.
  headers: { 'some': 'header' },

  // The data to send in the body of the request. Data objects will be
  // serialized as JSON.
  //
  // Note: if you would like to provide a Content-Type header other than
  // application/json you you must provide a string or readable stream, rather
  // than an object:
  // data: JSON.stringify({some: 'data'})
  // data: fs.readFile('./some-data.jpeg')
  data: {
    some: 'data'
  },

  // The max size of the http response content in bytes allowed.
  // Defaults to `0`, which is the same as unset.
  maxContentLength: 2000,

  // The max number of HTTP redirects to follow.
  // Defaults to 100.
  maxRedirects: 100,

  // The querystring parameters that will be encoded using `qs` and
  // appended to the url
  params: {
    querystring: 'parameters'
  },

  // By default, we use the `querystring` package in node core to serialize
  // querystring parameters.  You can override that and provide your
  // own implementation.
  paramsSerializer: (params) => {
    return qs.stringify(params);
  },

  // The timeout for the HTTP request in milliseconds. Defaults to 0.
  timeout: 1000,

  // Optional method to override making the actual HTTP request. Useful
  // for writing tests and instrumentation
  adapter?: async (options, defaultAdapter) => {
    const res = await defaultAdapter(options);
    res.data = {
      ...res.data,
      extraProperty: 'your extra property',
    };
    return res;
  };

  // The expected return type of the request.  Options are:
  // json | stream | blob | arraybuffer | text | unknown
  // Defaults to `unknown`.
  responseType: 'unknown',

  // The node.js http agent to use for the request.
  agent: someHttpsAgent,

  // Custom function to determine if the response is valid based on the
  // status code.  Defaults to (>= 200 && < 300)
  validateStatus: (status: number) => true,

  // Implementation of `fetch` to use when making the API call. By default,
  // will use the browser context if available, and fall back to `node-fetch`
  // in node.js otherwise.
  fetchImplementation?: typeof fetch;

  // Configuration for retrying of requests.
  retryConfig: {
    // The number of times to retry the request.  Defaults to 3.
    retry?: number;

    // The number of retries already attempted.
    currentRetryAttempt?: number;

    // The HTTP Methods that will be automatically retried.
    // Defaults to ['GET','PUT','HEAD','OPTIONS','DELETE']
    httpMethodsToRetry?: string[];

    // The HTTP response status codes that will automatically be retried.
    // Defaults to: [[100, 199], [408, 408], [429, 429], [500, 599]]
    statusCodesToRetry?: number[][];

    // Function to invoke when a retry attempt is made.
    onRetryAttempt?: (err: GaxiosError) => Promise<void> | void;

    // Function to invoke which determines if you should retry
    shouldRetry?: (err: GaxiosError) => Promise<boolean> | boolean;

    // When there is no response, the number of retries to attempt. Defaults to 2.
    noResponseRetries?: number;

    // The amount of time to initially delay the retry, in ms.  Defaults to 100ms.
    retryDelay?: number;
  },

  // Enables default configuration for retries.
  retry: boolean,

  // Cancelling a request requires the `abort-controller` library.
  // See https://github.com/bitinn/node-fetch#request-cancellation-with-abortsignal
  signal?: AbortSignal

  /**
   * A collection of parts to send as a `Content-Type: multipart/related` request.
   */
  multipart?: GaxiosMultipartOptions;

  /**
   * An optional proxy to use for requests.
   * Available via `process.env.HTTP_PROXY` and `process.env.HTTPS_PROXY` as well - with a preference for the this config option when multiple are available.
   * The `agent` option overrides this.
   *
   * @see {@link GaxiosOptions.noProxy}
   * @see {@link GaxiosOptions.agent}
   */
  proxy?: string | URL;
  /**
   * A list for excluding traffic for proxies.
   * Available via `process.env.NO_PROXY` as well as a common-separated list of strings - merged with any local `noProxy` rules.
   *
   * - When provided a string, it is matched by
   *   - Wildcard `*.` and `.` matching are available. (e.g. `.example.com` or `*.example.com`)
   * - When provided a URL, it is matched by the `.origin` property.
   *   - For example, requesting `https://example.com` with the following `noProxy`s would result in a no proxy use:
   *     - new URL('https://example.com')
   *     - new URL('https://example.com:443')
   *   - The following would be used with a proxy:
   *     - new URL('http://example.com:80')
   *     - new URL('https://example.com:8443')
   * - When provided a regular expression it is used to match the stringified URL
   *
   * @see {@link GaxiosOptions.proxy}
   */
  noProxy?: (string | URL | RegExp)[];

  /**
   * An experimental, customizable error redactor.
   *
   * Set `false` to disable.
   *
   * @remarks
   *
   * This does not replace the requirement for an active Data Loss Prevention (DLP) provider. For DLP suggestions, see:
   * - https://cloud.google.com/sensitive-data-protection/docs/redacting-sensitive-data#dlp_deidentify_replace_infotype-nodejs
   * - https://cloud.google.com/sensitive-data-protection/docs/infotypes-reference#credentials_and_secrets
   *
   * @experimental
   */
  errorRedactor?: typeof defaultErrorRedactor | false;
}
```

## License

[Apache-2.0](https://github.com/googleapis/gaxios/blob/master/LICENSE)
