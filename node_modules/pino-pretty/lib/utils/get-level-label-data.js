'use strict'

module.exports = getLevelLabelData
const { LEVELS, LEVEL_NAMES } = require('../constants')

/**
 * Given initial settings for custom levels/names and use of only custom props
 * get the level label that corresponds with a given level number
 *
 * @param {boolean} useOnlyCustomProps
 * @param {object} customLevels
 * @param {object} customLevelNames
 *
 * @returns {function} A function that takes a number level and returns the level's label string
 */
function getLevelLabelData (useOnlyCustomProps, customLevels, customLevelNames) {
  const levels = useOnlyCustomProps ? customLevels || LEVELS : Object.assign({}, LEVELS, customLevels)
  const levelNames = useOnlyCustomProps ? customLevelNames || LEVEL_NAMES : Object.assign({}, LEVEL_NAMES, customLevelNames)
  return function (level) {
    let levelNum = 'default'
    if (Number.isInteger(+level)) {
      levelNum = Object.prototype.hasOwnProperty.call(levels, level) ? level : levelNum
    } else {
      levelNum = Object.prototype.hasOwnProperty.call(levelNames, level.toLowerCase()) ? levelNames[level.toLowerCase()] : levelNum
    }

    return [levels[levelNum], levelNum]
  }
}
