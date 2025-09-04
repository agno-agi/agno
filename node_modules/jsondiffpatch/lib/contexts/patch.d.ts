import Context from './context.js';
import type { Delta } from '../types.js';
declare class PatchContext extends Context<unknown> {
    left: unknown;
    delta: Delta;
    pipe: 'patch';
    nested?: boolean;
    constructor(left: unknown, delta: Delta);
}
export default PatchContext;
