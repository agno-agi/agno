import BaseFormatter from './base.js';
const OPERATIONS = {
    add: 'add',
    remove: 'remove',
    replace: 'replace',
    move: 'move',
};
class JSONFormatter extends BaseFormatter {
    constructor() {
        super();
        this.includeMoveDestinations = true;
    }
    prepareContext(context) {
        super.prepareContext(context);
        context.result = [];
        context.path = [];
        context.pushCurrentOp = function (obj) {
            if (obj.op === 'add' || obj.op === 'replace') {
                this.result.push({
                    op: obj.op,
                    path: this.currentPath(),
                    value: obj.value,
                });
            }
            else if (obj.op === 'remove') {
                this.result.push({ op: obj.op, path: this.currentPath() });
            }
            else {
                obj;
            }
        };
        context.pushMoveOp = function (to) {
            const from = this.currentPath();
            this.result.push({
                op: OPERATIONS.move,
                from,
                path: this.toPath(to),
            });
        };
        context.currentPath = function () {
            return `/${this.path.join('/')}`;
        };
        context.toPath = function (toPath) {
            const to = this.path.slice();
            to[to.length - 1] = toPath;
            return `/${to.join('/')}`;
        };
    }
    typeFormattterErrorFormatter(context, err) {
        // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
        context.out(`[ERROR] ${err}`);
    }
    rootBegin() { }
    rootEnd() { }
    nodeBegin({ path }, key, leftKey) {
        path.push(leftKey);
    }
    nodeEnd({ path }) {
        path.pop();
    }
    format_unchanged() { }
    format_movedestination() { }
    format_node(context, delta, left) {
        this.formatDeltaChildren(context, delta, left);
    }
    format_added(context, delta) {
        context.pushCurrentOp({ op: OPERATIONS.add, value: delta[0] });
    }
    format_modified(context, delta) {
        context.pushCurrentOp({ op: OPERATIONS.replace, value: delta[1] });
    }
    format_deleted(context) {
        context.pushCurrentOp({ op: OPERATIONS.remove });
    }
    format_moved(context, delta) {
        const to = delta[1];
        context.pushMoveOp(to);
    }
    format_textdiff() {
        throw new Error('Not implemented');
    }
    format(delta, left) {
        const context = {};
        this.prepareContext(context);
        const preparedContext = context;
        this.recurse(preparedContext, delta, left);
        return preparedContext.result;
    }
}
export default JSONFormatter;
const last = (arr) => arr[arr.length - 1];
const sortBy = (arr, pred) => {
    arr.sort(pred);
    return arr;
};
const compareByIndexDesc = (indexA, indexB) => {
    const lastA = parseInt(indexA, 10);
    const lastB = parseInt(indexB, 10);
    if (!(isNaN(lastA) || isNaN(lastB))) {
        return lastB - lastA;
    }
    else {
        return 0;
    }
};
const opsByDescendingOrder = (removeOps) => sortBy(removeOps, (a, b) => {
    const splitA = a.path.split('/');
    const splitB = b.path.split('/');
    if (splitA.length !== splitB.length) {
        return splitA.length - splitB.length;
    }
    else {
        return compareByIndexDesc(last(splitA), last(splitB));
    }
});
export const partitionOps = (arr, fns) => {
    const initArr = Array(fns.length + 1)
        .fill(undefined)
        .map(() => []);
    return arr
        .map((item) => {
        let position = fns.map((fn) => fn(item)).indexOf(true);
        if (position < 0) {
            position = fns.length;
        }
        return { item, position };
    })
        .reduce((acc, item) => {
        acc[item.position].push(item.item);
        return acc;
    }, initArr);
};
const isMoveOp = ({ op }) => op === 'move';
const isRemoveOp = ({ op }) => op === 'remove';
const reorderOps = (diff) => {
    const [moveOps, removedOps, restOps] = partitionOps(diff, [
        isMoveOp,
        isRemoveOp,
    ]);
    const removeOpsReverse = opsByDescendingOrder(removedOps);
    return [...removeOpsReverse, ...moveOps, ...restOps];
};
let defaultInstance;
export const format = (delta, left) => {
    if (!defaultInstance) {
        defaultInstance = new JSONFormatter();
    }
    return reorderOps(defaultInstance.format(delta, left));
};
export const log = (delta, left) => {
    console.log(format(delta, left));
};
