import DiffContext from '../contexts/diff.js';
import PatchContext from '../contexts/patch.js';
import ReverseContext from '../contexts/reverse.js';
export const collectChildrenDiffFilter = (context) => {
    if (!context || !context.children) {
        return;
    }
    const length = context.children.length;
    let child;
    let result = context.result;
    for (let index = 0; index < length; index++) {
        child = context.children[index];
        if (typeof child.result === 'undefined') {
            continue;
        }
        result = result || {};
        result[child.childName] = child.result;
    }
    if (result && context.leftIsArray) {
        result._t = 'a';
    }
    context.setResult(result).exit();
};
collectChildrenDiffFilter.filterName = 'collectChildren';
export const objectsDiffFilter = (context) => {
    if (context.leftIsArray || context.leftType !== 'object') {
        return;
    }
    const left = context.left;
    const right = context.right;
    let name;
    let child;
    const propertyFilter = context.options.propertyFilter;
    for (name in left) {
        if (!Object.prototype.hasOwnProperty.call(left, name)) {
            continue;
        }
        if (propertyFilter && !propertyFilter(name, context)) {
            continue;
        }
        child = new DiffContext(left[name], right[name]);
        context.push(child, name);
    }
    for (name in right) {
        if (!Object.prototype.hasOwnProperty.call(right, name)) {
            continue;
        }
        if (propertyFilter && !propertyFilter(name, context)) {
            continue;
        }
        if (typeof left[name] === 'undefined') {
            child = new DiffContext(undefined, right[name]);
            context.push(child, name);
        }
    }
    if (!context.children || context.children.length === 0) {
        context.setResult(undefined).exit();
        return;
    }
    context.exit();
};
objectsDiffFilter.filterName = 'objects';
export const patchFilter = function nestedPatchFilter(context) {
    if (!context.nested) {
        return;
    }
    const nestedDelta = context.delta;
    if (nestedDelta._t) {
        return;
    }
    const objectDelta = nestedDelta;
    let name;
    let child;
    for (name in objectDelta) {
        child = new PatchContext(context.left[name], objectDelta[name]);
        context.push(child, name);
    }
    context.exit();
};
patchFilter.filterName = 'objects';
export const collectChildrenPatchFilter = function collectChildrenPatchFilter(context) {
    if (!context || !context.children) {
        return;
    }
    const deltaWithChildren = context.delta;
    if (deltaWithChildren._t) {
        return;
    }
    const object = context.left;
    const length = context.children.length;
    let child;
    for (let index = 0; index < length; index++) {
        child = context.children[index];
        const property = child.childName;
        if (Object.prototype.hasOwnProperty.call(context.left, property) &&
            child.result === undefined) {
            delete object[property];
        }
        else if (object[property] !== child.result) {
            object[property] = child.result;
        }
    }
    context.setResult(object).exit();
};
collectChildrenPatchFilter.filterName = 'collectChildren';
export const reverseFilter = function nestedReverseFilter(context) {
    if (!context.nested) {
        return;
    }
    const nestedDelta = context.delta;
    if (nestedDelta._t) {
        return;
    }
    const objectDelta = context.delta;
    let name;
    let child;
    for (name in objectDelta) {
        child = new ReverseContext(objectDelta[name]);
        context.push(child, name);
    }
    context.exit();
};
reverseFilter.filterName = 'objects';
export const collectChildrenReverseFilter = (context) => {
    if (!context || !context.children) {
        return;
    }
    const deltaWithChildren = context.delta;
    if (deltaWithChildren._t) {
        return;
    }
    const length = context.children.length;
    let child;
    const delta = {};
    for (let index = 0; index < length; index++) {
        child = context.children[index];
        const property = child.childName;
        if (delta[property] !== child.result) {
            delta[property] = child.result;
        }
    }
    context.setResult(delta).exit();
};
collectChildrenReverseFilter.filterName = 'collectChildren';
