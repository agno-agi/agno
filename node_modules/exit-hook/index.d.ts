/**
@callback onExit
@param {number} signal - The exit code.
*/

/**
Run some code when the process exits.

The `process.on('exit')` event doesn't catch all the ways a process can exit.

This is useful for cleaning synchronously before exiting.

@param {onExit} onExit - The callback function to execute when the process exits.
@returns A function that removes the hook when called.

@example
```
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

// Removing an exit hook:
const unsubscribe = exitHook(() => {});

unsubscribe();
```
*/
export default function exitHook(onExit: (signal: number) => void): () => void;

/**
Run code asynchronously when the process exits.

@see https://github.com/sindresorhus/exit-hook/blob/main/readme.md#asynchronous-exit-notes
@param {onExit} onExit - The callback function to execute when the process exits via `gracefulExit`, and will be wrapped in `Promise.resolve`.
@returns A function that removes the hook when called.

@example
```
import {asyncExitHook} from 'exit-hook';

asyncExitHook(() => {
	console.log('Exiting');
}, {
	wait: 500
});

throw new Error('🦄');

//=> 'Exiting'

// Removing an exit hook:
const unsubscribe = asyncExitHook(() => {}, {wait: 500});

unsubscribe();
```
*/
export function asyncExitHook(onExit: (signal: number) => (void | Promise<void>), options: Options): () => void;

/**
Exit the process and make a best-effort to complete all asynchronous hooks.

If you are using `asyncExitHook`, consider using `gracefulExit()` instead of `process.exit()` to ensure all asynchronous tasks are given an opportunity to run.

@param signal - The exit code to use. Same as the argument to `process.exit()`.
@see https://github.com/sindresorhus/exit-hook/blob/main/readme.md#asynchronous-exit-notes

@example
```
import {asyncExitHook, gracefulExit} from 'exit-hook';

asyncExitHook(() => {
	console.log('Exiting');
}, {
	wait: 500
});

// Instead of `process.exit()`
gracefulExit();
```
*/
export function gracefulExit(signal?: number): void;

export type Options = {
	/**
	The amount of time in milliseconds that the `onExit` function is expected to take. When multiple async handlers are registered, the longest `wait` time will be used.
	*/
	readonly wait: number;
};
