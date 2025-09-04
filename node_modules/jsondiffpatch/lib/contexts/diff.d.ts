import Context from './context.js';
import type { Delta } from '../types.js';
declare class DiffContext extends Context<Delta> {
    left: unknown;
    right: unknown;
    pipe: 'diff';
    leftType?: string;
    rightType?: string;
    leftIsArray?: boolean;
    rightIsArray?: boolean;
    constructor(left: unknown, right: unknown);
    setResult(result: Delta): this;
}
export default DiffContext;
