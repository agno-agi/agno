import Context from './context.js';
import type { Delta } from '../types.js';
declare class ReverseContext extends Context<Delta> {
    delta: Delta;
    pipe: 'reverse';
    nested?: boolean;
    newName?: `_${number}`;
    constructor(delta: Delta);
}
export default ReverseContext;
