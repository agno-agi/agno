/**
Throttle a function to limit its execution rate.

Creates a throttled function that limits calls to the original function to at most once every `wait` milliseconds. It guarantees execution after the final invocation and maintains the last context (`this`) and arguments.

@param function_ - The function to be throttled.
@param wait - The number of milliseconds to throttle invocations to.
@returns A new throttled version of the provided function.

@example
```
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
*/
declare function throttle<T extends (...arguments_: any[]) => unknown>(function_: T, wait: number): T;

export = throttle;
