import type { Options } from '../types.js';
export default abstract class Context<TResult> {
    abstract pipe: string;
    result?: TResult;
    hasResult?: boolean;
    exiting?: boolean;
    parent?: this;
    childName?: string | number;
    root?: this;
    options?: Options;
    children?: this[];
    nextAfterChildren?: this | null;
    next?: this | null;
    setResult(result: TResult): this;
    exit(): this;
    push(child: this, name?: string | number): this;
}
