// eslint-disable-next-line @typescript-eslint/no-explicit-any
class Pipe {
    constructor(name) {
        this.name = name;
        this.filters = [];
    }
    process(input) {
        if (!this.processor) {
            throw new Error('add this pipe to a processor before using it');
        }
        const debug = this.debug;
        const length = this.filters.length;
        const context = input;
        for (let index = 0; index < length; index++) {
            const filter = this.filters[index];
            if (debug) {
                this.log(`filter: ${filter.filterName}`);
            }
            filter(context);
            if (typeof context === 'object' && context.exiting) {
                context.exiting = false;
                break;
            }
        }
        if (!context.next && this.resultCheck) {
            this.resultCheck(context);
        }
    }
    log(msg) {
        console.log(`[jsondiffpatch] ${this.name} pipe, ${msg}`);
    }
    append(...args) {
        this.filters.push(...args);
        return this;
    }
    prepend(...args) {
        this.filters.unshift(...args);
        return this;
    }
    indexOf(filterName) {
        if (!filterName) {
            throw new Error('a filter name is required');
        }
        for (let index = 0; index < this.filters.length; index++) {
            const filter = this.filters[index];
            if (filter.filterName === filterName) {
                return index;
            }
        }
        throw new Error(`filter not found: ${filterName}`);
    }
    list() {
        return this.filters.map((f) => f.filterName);
    }
    after(filterName, ...params) {
        const index = this.indexOf(filterName);
        this.filters.splice(index + 1, 0, ...params);
        return this;
    }
    before(filterName, ...params) {
        const index = this.indexOf(filterName);
        this.filters.splice(index, 0, ...params);
        return this;
    }
    replace(filterName, ...params) {
        const index = this.indexOf(filterName);
        this.filters.splice(index, 1, ...params);
        return this;
    }
    remove(filterName) {
        const index = this.indexOf(filterName);
        this.filters.splice(index, 1);
        return this;
    }
    clear() {
        this.filters.length = 0;
        return this;
    }
    shouldHaveResult(should) {
        if (should === false) {
            this.resultCheck = null;
            return;
        }
        if (this.resultCheck) {
            return;
        }
        this.resultCheck = (context) => {
            if (!context.hasResult) {
                console.log(context);
                const error = new Error(`${this.name} failed`);
                error.noResult = true;
                throw error;
            }
        };
        return this;
    }
}
export default Pipe;
