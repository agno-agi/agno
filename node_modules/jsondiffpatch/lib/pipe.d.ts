import type Context from './contexts/context.js';
import type Processor from './processor.js';
import type { Filter } from './types.js';
declare class Pipe<TContext extends Context<any>> {
    name: string;
    filters: Filter<TContext>[];
    processor?: Processor;
    debug?: boolean;
    resultCheck?: ((context: TContext) => void) | null;
    constructor(name: string);
    process(input: TContext): void;
    log(msg: string): void;
    append(...args: Filter<TContext>[]): this;
    prepend(...args: Filter<TContext>[]): this;
    indexOf(filterName: string): number;
    list(): string[];
    after(filterName: string, ...params: Filter<TContext>[]): this;
    before(filterName: string, ...params: Filter<TContext>[]): this;
    replace(filterName: string, ...params: Filter<TContext>[]): this;
    remove(filterName: string): this;
    clear(): this;
    shouldHaveResult(should?: boolean): this | undefined;
}
export default Pipe;
