export const diffFilter = function trivialMatchesDiffFilter(context) {
    if (context.left === context.right) {
        context.setResult(undefined).exit();
        return;
    }
    if (typeof context.left === 'undefined') {
        if (typeof context.right === 'function') {
            throw new Error('functions are not supported');
        }
        context.setResult([context.right]).exit();
        return;
    }
    if (typeof context.right === 'undefined') {
        context.setResult([context.left, 0, 0]).exit();
        return;
    }
    if (typeof context.left === 'function' ||
        typeof context.right === 'function') {
        throw new Error('functions are not supported');
    }
    context.leftType = context.left === null ? 'null' : typeof context.left;
    context.rightType = context.right === null ? 'null' : typeof context.right;
    if (context.leftType !== context.rightType) {
        context.setResult([context.left, context.right]).exit();
        return;
    }
    if (context.leftType === 'boolean' || context.leftType === 'number') {
        context.setResult([context.left, context.right]).exit();
        return;
    }
    if (context.leftType === 'object') {
        context.leftIsArray = Array.isArray(context.left);
    }
    if (context.rightType === 'object') {
        context.rightIsArray = Array.isArray(context.right);
    }
    if (context.leftIsArray !== context.rightIsArray) {
        context.setResult([context.left, context.right]).exit();
        return;
    }
    if (context.left instanceof RegExp) {
        if (context.right instanceof RegExp) {
            context
                .setResult([context.left.toString(), context.right.toString()])
                .exit();
        }
        else {
            context.setResult([context.left, context.right]).exit();
        }
    }
};
diffFilter.filterName = 'trivial';
export const patchFilter = function trivialMatchesPatchFilter(context) {
    if (typeof context.delta === 'undefined') {
        context.setResult(context.left).exit();
        return;
    }
    context.nested = !Array.isArray(context.delta);
    if (context.nested) {
        return;
    }
    const nonNestedDelta = context.delta;
    if (nonNestedDelta.length === 1) {
        context.setResult(nonNestedDelta[0]).exit();
        return;
    }
    if (nonNestedDelta.length === 2) {
        if (context.left instanceof RegExp) {
            const regexArgs = /^\/(.*)\/([gimyu]+)$/.exec(nonNestedDelta[1]);
            if (regexArgs) {
                context.setResult(new RegExp(regexArgs[1], regexArgs[2])).exit();
                return;
            }
        }
        context.setResult(nonNestedDelta[1]).exit();
        return;
    }
    if (nonNestedDelta.length === 3 && nonNestedDelta[2] === 0) {
        context.setResult(undefined).exit();
    }
};
patchFilter.filterName = 'trivial';
export const reverseFilter = function trivialReferseFilter(context) {
    if (typeof context.delta === 'undefined') {
        context.setResult(context.delta).exit();
        return;
    }
    context.nested = !Array.isArray(context.delta);
    if (context.nested) {
        return;
    }
    const nonNestedDelta = context.delta;
    if (nonNestedDelta.length === 1) {
        context.setResult([nonNestedDelta[0], 0, 0]).exit();
        return;
    }
    if (nonNestedDelta.length === 2) {
        context.setResult([nonNestedDelta[1], nonNestedDelta[0]]).exit();
        return;
    }
    if (nonNestedDelta.length === 3 && nonNestedDelta[2] === 0) {
        context.setResult([nonNestedDelta[0]]).exit();
    }
};
reverseFilter.filterName = 'trivial';
