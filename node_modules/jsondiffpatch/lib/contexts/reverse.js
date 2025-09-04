import Context from './context.js';
class ReverseContext extends Context {
    constructor(delta) {
        super();
        this.delta = delta;
        this.pipe = 'reverse';
    }
}
export default ReverseContext;
