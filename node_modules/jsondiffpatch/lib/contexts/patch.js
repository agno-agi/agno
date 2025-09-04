import Context from './context.js';
class PatchContext extends Context {
    constructor(left, delta) {
        super();
        this.left = left;
        this.delta = delta;
        this.pipe = 'patch';
    }
}
export default PatchContext;
