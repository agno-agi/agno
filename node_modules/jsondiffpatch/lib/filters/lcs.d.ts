import type { MatchContext } from './arrays.js';
interface Subsequence {
    sequence: unknown[];
    indices1: number[];
    indices2: number[];
}
declare const _default: {
    get: (array1: readonly unknown[], array2: readonly unknown[], match?: ((array1: readonly unknown[], array2: readonly unknown[], index1: number, index2: number, context: MatchContext) => boolean | undefined) | undefined, context?: MatchContext | undefined) => Subsequence;
};
export default _default;
