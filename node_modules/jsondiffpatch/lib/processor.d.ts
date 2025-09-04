import type Context from './contexts/context.js';
import type Pipe from './pipe.js';
import type { Options } from './types.js';
import type DiffContext from './contexts/diff.js';
import type PatchContext from './contexts/patch.js';
import type ReverseContext from './contexts/reverse.js';
declare class Processor {
    selfOptions: Options;
    pipes: {
        diff: Pipe<DiffContext>;
        patch: Pipe<PatchContext>;
        reverse: Pipe<ReverseContext>;
    };
    constructor(options?: Options);
    options(options?: Options): Options;
    pipe<TContext extends Context<any>>(name: string | Pipe<TContext>, pipeArg?: Pipe<TContext>): Pipe<DiffContext> | Pipe<PatchContext> | Pipe<ReverseContext> | Pipe<TContext>;
    process<TContext extends Context<any>>(input: TContext, pipe?: Pipe<TContext>): TContext['result'] | undefined;
}
export default Processor;
