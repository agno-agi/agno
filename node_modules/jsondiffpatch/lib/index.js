import DiffPatcher from './diffpatcher.js';
import dateReviver from './date-reviver.js';
export { DiffPatcher, dateReviver };
export function create(options) {
    return new DiffPatcher(options);
}
let defaultInstance;
export function diff(left, right) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher();
    }
    return defaultInstance.diff(left, right);
}
export function patch(left, delta) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher();
    }
    return defaultInstance.patch(left, delta);
}
export function unpatch(right, delta) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher();
    }
    return defaultInstance.unpatch(right, delta);
}
export function reverse(delta) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher();
    }
    return defaultInstance.reverse(delta);
}
export function clone(value) {
    if (!defaultInstance) {
        defaultInstance = new DiffPatcher();
    }
    return defaultInstance.clone(value);
}
