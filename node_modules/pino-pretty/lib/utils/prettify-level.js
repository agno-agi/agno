'use strict'

module.exports = prettifyLevel

const getPropertyValue = require('./get-property-value')

/**
 * @typedef {object} PrettifyLevelParams
 * @property {object} log The log object.
 * @property {PrettyContext} context The context object built from parsing
 * the options.
 */

/**
 * Checks if the passed in log has a `level` value and returns a prettified
 * string for that level if so.
 *
 * @param {PrettifyLevelParams} input
 *
 * @returns {undefined|string} If `log` does not have a `level` property then
 * `undefined` will be returned. Otherwise, a string from the specified
 * `colorizer` is returned.
 */
function prettifyLevel ({ log, context }) {
  const {
    colorizer,
    customLevels,
    customLevelNames,
    levelKey,
    getLevelLabelData
  } = context
  const prettifier = context.customPrettifiers?.level
  const output = getPropertyValue(log, levelKey)
  if (output === undefined) return undefined
  const labelColorized = colorizer(output, { customLevels, customLevelNames })
  if (prettifier) {
    const [label] = getLevelLabelData(output)
    return prettifier(output, levelKey, log, { label, labelColorized, colors: colorizer.colors })
  }
  return labelColorized
}
