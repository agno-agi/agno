import DiffMatchPatch from 'diff-match-patch';
import DiffPatcher from './diffpatcher.js';
import dateReviver from './date-reviver.js';
export { DiffPatcher, dateReviver };
export function create(options) {
    return new DiffPatcher(Object.assign(Object.assign({}, options), { textDiff: Object.assign(Object.assign({}, options === null || options === void 0 ? void 0 : options.textDiff), { diffMatchPatch: DiffMatchPatch }) }));
}
let defaultInstance;
export function diff(left, right) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher({
            textDiff: { diffMatchPatch: DiffMatchPatch },
        });
    }
    return defaultInstance.diff(left, right);
}
export function patch(left, delta) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher({
            textDiff: { diffMatchPatch: DiffMatchPatch },
        });
    }
    return defaultInstance.patch(left, delta);
}
export function unpatch(right, delta) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher({
            textDiff: { diffMatchPatch: DiffMatchPatch },
        });
    }
    return defaultInstance.unpatch(right, delta);
}
export function reverse(delta) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher({
            textDiff: { diffMatchPatch: DiffMatchPatch },
        });
    }
    return defaultInstance.reverse(delta);
}
export function clone(value) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher({
            textDiff: { diffMatchPatch: DiffMatchPatch },
        });
    }
    return defaultInstance.clone(value);
}
