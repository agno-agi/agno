const trimUnderscore = (str) => {
    if (str.substring(0, 1) === '_') {
        return str.slice(1);
    }
    return str;
};
const arrayKeyToSortNumber = (key) => {
    if (key === '_t') {
        return -1;
    }
    else {
        if (key.substring(0, 1) === '_') {
            return parseInt(key.slice(1), 10);
        }
        else {
            return parseInt(key, 10) + 0.1;
        }
    }
};
const arrayKeyComparer = (key1, key2) => arrayKeyToSortNumber(key1) - arrayKeyToSortNumber(key2);
class BaseFormatter {
    format(delta, left) {
        const context = {};
        this.prepareContext(context);
        const preparedContext = context;
        this.recurse(preparedContext, delta, left);
        return this.finalize(preparedContext);
    }
    prepareContext(context) {
        context.buffer = [];
        context.out = function (...args) {
            this.buffer.push(...args);
        };
    }
    typeFormattterNotFound(context, deltaType) {
        throw new Error(`cannot format delta type: ${deltaType}`);
    }
    /* eslint-disable @typescript-eslint/no-unused-vars */
    typeFormattterErrorFormatter(context, err, delta, leftValue, key, leftKey, movedFrom) { }
    /* eslint-enable @typescript-eslint/no-unused-vars */
    finalize({ buffer }) {
        if (Array.isArray(buffer)) {
            return buffer.join('');
        }
    }
    recurse(context, delta, left, key, leftKey, movedFrom, isLast) {
        const useMoveOriginHere = delta && movedFrom;
        const leftValue = useMoveOriginHere ? movedFrom.value : left;
        if (typeof delta === 'undefined' && typeof key === 'undefined') {
            return undefined;
        }
        const type = this.getDeltaType(delta, movedFrom);
        const nodeType = type === 'node'
            ? delta._t === 'a'
                ? 'array'
                : 'object'
            : '';
        if (typeof key !== 'undefined') {
            this.nodeBegin(context, key, leftKey, type, nodeType, isLast);
        }
        else {
            this.rootBegin(context, type, nodeType);
        }
        let typeFormattter;
        try {
            typeFormattter =
                type !== 'unknown'
                    ? this[`format_${type}`]
                    : this.typeFormattterNotFound(context, type);
            typeFormattter.call(this, context, delta, leftValue, key, leftKey, movedFrom);
        }
        catch (err) {
            this.typeFormattterErrorFormatter(context, err, delta, leftValue, key, leftKey, movedFrom);
            if (typeof console !== 'undefined' && console.error) {
                console.error(err.stack);
            }
        }
        if (typeof key !== 'undefined') {
            this.nodeEnd(context, key, leftKey, type, nodeType, isLast);
        }
        else {
            this.rootEnd(context, type, nodeType);
        }
    }
    formatDeltaChildren(context, delta, left) {
        this.forEachDeltaKey(delta, left, (key, leftKey, movedFrom, isLast) => {
            this.recurse(context, delta[key], left ? left[leftKey] : undefined, key, leftKey, movedFrom, isLast);
        });
    }
    forEachDeltaKey(delta, left, fn) {
        const keys = Object.keys(delta);
        const arrayKeys = delta._t === 'a';
        const moveDestinations = {};
        let name;
        if (typeof left !== 'undefined') {
            for (name in left) {
                if (Object.prototype.hasOwnProperty.call(left, name)) {
                    if (typeof delta[name] === 'undefined' &&
                        (!arrayKeys ||
                            typeof delta[`_${name}`] ===
                                'undefined')) {
                        keys.push(name);
                    }
                }
            }
        }
        // look for move destinations
        for (name in delta) {
            if (Object.prototype.hasOwnProperty.call(delta, name)) {
                const value = delta[name];
                if (Array.isArray(value) && value[2] === 3) {
                    const movedDelta = value;
                    moveDestinations[`${movedDelta[1]}`] = {
                        key: name,
                        value: left && left[parseInt(name.substring(1), 10)],
                    };
                    if (this.includeMoveDestinations !== false) {
                        if (typeof left === 'undefined' &&
                            typeof delta[movedDelta[1]] === 'undefined') {
                            keys.push(movedDelta[1].toString());
                        }
                    }
                }
            }
        }
        if (arrayKeys) {
            keys.sort(arrayKeyComparer);
        }
        else {
            keys.sort();
        }
        for (let index = 0, length = keys.length; index < length; index++) {
            const key = keys[index];
            if (arrayKeys && key === '_t') {
                continue;
            }
            const leftKey = arrayKeys ? parseInt(trimUnderscore(key), 10) : key;
            const isLast = index === length - 1;
            fn(key, leftKey, moveDestinations[leftKey], isLast);
        }
    }
    getDeltaType(delta, movedFrom) {
        if (typeof delta === 'undefined') {
            if (typeof movedFrom !== 'undefined') {
                return 'movedestination';
            }
            return 'unchanged';
        }
        if (Array.isArray(delta)) {
            if (delta.length === 1) {
                return 'added';
            }
            if (delta.length === 2) {
                return 'modified';
            }
            if (delta.length === 3 && delta[2] === 0) {
                return 'deleted';
            }
            if (delta.length === 3 && delta[2] === 2) {
                return 'textdiff';
            }
            if (delta.length === 3 && delta[2] === 3) {
                return 'moved';
            }
        }
        else if (typeof delta === 'object') {
            return 'node';
        }
        return 'unknown';
    }
    parseTextDiff(value) {
        const output = [];
        const lines = value.split('\n@@ ');
        for (let i = 0, l = lines.length; i < l; i++) {
            const line = lines[i];
            const lineOutput = {
                pieces: [],
            };
            const location = /^(?:@@ )?[-+]?(\d+),(\d+)/.exec(line).slice(1);
            lineOutput.location = {
                line: location[0],
                chr: location[1],
            };
            const pieces = line.split('\n').slice(1);
            for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
                const piece = pieces[pieceIndex];
                if (!piece.length) {
                    continue;
                }
                const pieceOutput = {
                    type: 'context',
                };
                if (piece.substring(0, 1) === '+') {
                    pieceOutput.type = 'added';
                }
                else if (piece.substring(0, 1) === '-') {
                    pieceOutput.type = 'deleted';
                }
                pieceOutput.text = piece.slice(1);
                lineOutput.pieces.push(pieceOutput);
            }
            output.push(lineOutput);
        }
        return output;
    }
}
export default BaseFormatter;
