/*

LCS implementation that supports arrays or strings

reference: http://en.wikipedia.org/wiki/Longest_common_subsequence_problem

*/
const defaultMatch = function (array1, array2, index1, index2) {
    return array1[index1] === array2[index2];
};
const lengthMatrix = function (array1, array2, match, context) {
    const len1 = array1.length;
    const len2 = array2.length;
    let x, y;
    // initialize empty matrix of len1+1 x len2+1
    const matrix = new Array(len1 + 1);
    for (x = 0; x < len1 + 1; x++) {
        matrix[x] = new Array(len2 + 1);
        for (y = 0; y < len2 + 1; y++) {
            matrix[x][y] = 0;
        }
    }
    matrix.match = match;
    // save sequence lengths for each coordinate
    for (x = 1; x < len1 + 1; x++) {
        for (y = 1; y < len2 + 1; y++) {
            if (match(array1, array2, x - 1, y - 1, context)) {
                matrix[x][y] = matrix[x - 1][y - 1] + 1;
            }
            else {
                matrix[x][y] = Math.max(matrix[x - 1][y], matrix[x][y - 1]);
            }
        }
    }
    return matrix;
};
const backtrack = function (matrix, array1, array2, context) {
    let index1 = array1.length;
    let index2 = array2.length;
    const subsequence = {
        sequence: [],
        indices1: [],
        indices2: [],
    };
    while (index1 !== 0 && index2 !== 0) {
        const sameLetter = matrix.match(array1, array2, index1 - 1, index2 - 1, context);
        if (sameLetter) {
            subsequence.sequence.unshift(array1[index1 - 1]);
            subsequence.indices1.unshift(index1 - 1);
            subsequence.indices2.unshift(index2 - 1);
            --index1;
            --index2;
        }
        else {
            const valueAtMatrixAbove = matrix[index1][index2 - 1];
            const valueAtMatrixLeft = matrix[index1 - 1][index2];
            if (valueAtMatrixAbove > valueAtMatrixLeft) {
                --index2;
            }
            else {
                --index1;
            }
        }
    }
    return subsequence;
};
const get = function (array1, array2, match, context) {
    const innerContext = context || {};
    const matrix = lengthMatrix(array1, array2, match || defaultMatch, innerContext);
    return backtrack(matrix, array1, array2, innerContext);
};
export default {
    get,
};
