# exit-hook

> Run some code when the process exits

The `process.on('exit')` event doesn't catch all the ways a process can exit.

This package is useful for cleaning up before exiting.

## Install

```sh
npm install exit-hook
```

## Usage

```js
import exitHook from 'exit-hook';

exitHook(signal => {
	console.log(`Exiting with signal: ${signal}`);
});

// You can add multiple hooks, even across files
exitHook(() => {
	console.log('Exiting 2');
});

throw new Error('🦄');

//=> 'Exiting'
//=> 'Exiting 2'
```

Removing an exit hook:

```js
import exitHook from 'exit-hook';

const unsubscribe = exitHook(() => {});

unsubscribe();
```

## API

### exitHook(onExit)

Register a function to run during `process.exit`.

Returns a function that removes the hook when called.

#### onExit

Type: `(signal: number) => void`

The callback function to execute when the process exits.

### asyncExitHook(onExit, options)

Register a function to run during `gracefulExit`.

Returns a function that removes the hook when called.

Please see [Async Notes](#asynchronous-exit-notes) for considerations when using the asynchronous API.

#### onExit

Type: `(signal: number) => (void | Promise<void>)`

The callback function to execute when the process exits via `gracefulExit`, and will be wrapped in `Promise.resolve`.

#### options

Type: `object`

##### wait

Type: `number`

The amount of time in milliseconds that the `onExit` function is expected to take. When multiple async handlers are registered, the longest `wait` time will be used.

```js
import {asyncExitHook} from 'exit-hook';

asyncExitHook(async () => {
	console.log('Exiting');
}, {
	wait: 300
});

throw new Error('🦄');

//=> 'Exiting'
```

Removing an asynchronous exit hook:

```js
import {asyncExitHook} from 'exit-hook';

const unsubscribe = asyncExitHook(async () => {
	console.log('Exiting');
}, {
	wait: 300
});

unsubscribe();
```

### gracefulExit(signal?: number): void

Exit the process and make a best-effort to complete all asynchronous hooks.

If you are using `asyncExitHook`, consider using `gracefulExit()` instead of `process.exit()` to ensure all asynchronous tasks are given an opportunity to run.

```js
import {gracefulExit} from 'exit-hook';

gracefulExit();
```

#### signal

Type: `number`\
Default: `0`

The exit code to use. Same as the argument to `process.exit()`.

## Asynchronous Exit Notes

**tl;dr** If you have 100% control over how your process terminates, then you can swap `exitHook` and `process.exit` for `asyncExitHook` and `gracefulExit` respectively. Otherwise, keep reading to understand important tradeoffs if you're using `asyncExitHook`.

Node.js does not offer an asynchronous shutdown API by default [#1](https://github.com/nodejs/node/discussions/29480#discussioncomment-99213) [#2](https://github.com/nodejs/node/discussions/29480#discussioncomment-99217), so `asyncExitHook` and `gracefulExit` will make a "best effort" attempt to shut down the process and run your asynchronous tasks.

If you have asynchronous hooks registered and your Node.js process is terminated in a synchronous manner, a `SYNCHRONOUS TERMINATION NOTICE` error will be logged to the console. To avoid this, ensure you're only exiting via `gracefulExit` or that an upstream process manager is sending a `SIGINT` or `SIGTERM` signal to Node.js.

Asynchronous hooks should make a "best effort" to perform their tasks within the `wait` time, but also be written to assume they may not complete their tasks before termination.
