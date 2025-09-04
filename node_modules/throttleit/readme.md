# throttleit

> Throttle a function to limit its execution rate

## Install

```sh
npm install throttleit
```

## Usage

```js
import throttle from 'throttleit';

// Throttling a function that processes data.
function processData(data) {
	console.log('Processing:', data);

	// Add data processing logic here.
}

// Throttle the `processData` function to be called at most once every 3 seconds.
const throttledProcessData = throttle(processData, 3000);

// Simulate calling the function multiple times with different data.
throttledProcessData('Data 1');
throttledProcessData('Data 2');
throttledProcessData('Data 3');
```

## API

### throttle(function, wait)

Creates a throttled function that limits calls to the original function to at most once every `wait` milliseconds. It guarantees execution after the final invocation and maintains the last context (`this`) and arguments.

#### function

Type: `function`

The function to be throttled.

#### wait

Type: `number`

The number of milliseconds to throttle invocations to.

## Related

- [p-throttle](https://github.com/sindresorhus/p-throttle) - Throttle async functions
- [debounce](https://github.com/sindresorhus/debounce) - Delay function calls until a set time elapses after the last invocation
