'use strict'

module.exports = prettifyMetadata

/**
 * @typedef {object} PrettifyMetadataParams
 * @property {object} log The log that may or may not contain metadata to
 * be prettified.
 * @property {PrettyContext} context The context object built from parsing
 * the options.
 */

/**
 * Prettifies metadata that is usually present in a Pino log line. It looks for
 * fields `name`, `pid`, `hostname`, and `caller` and returns a formatted string using
 * the fields it finds.
 *
 * @param {PrettifyMetadataParams} input
 *
 * @returns {undefined|string} If no metadata is found then `undefined` is
 * returned. Otherwise, a string of prettified metadata is returned.
 */
function prettifyMetadata ({ log, context }) {
  const { customPrettifiers: prettifiers, colorizer } = context
  let line = ''

  if (log.name || log.pid || log.hostname) {
    line += '('

    if (log.name) {
      line += prettifiers.name
        ? prettifiers.name(log.name, 'name', log, { colors: colorizer.colors })
        : log.name
    }

    if (log.pid) {
      const prettyPid = prettifiers.pid
        ? prettifiers.pid(log.pid, 'pid', log, { colors: colorizer.colors })
        : log.pid
      if (log.name && log.pid) {
        line += '/' + prettyPid
      } else {
        line += prettyPid
      }
    }

    if (log.hostname) {
      // If `pid` and `name` were in the ignore keys list then we don't need
      // the leading space.
      const prettyHostname = prettifiers.hostname
        ? prettifiers.hostname(log.hostname, 'hostname', log, { colors: colorizer.colors })
        : log.hostname

      line += `${line === '(' ? 'on' : ' on'} ${prettyHostname}`
    }

    line += ')'
  }

  if (log.caller) {
    const prettyCaller = prettifiers.caller
      ? prettifiers.caller(log.caller, 'caller', log, { colors: colorizer.colors })
      : log.caller

    line += `${line === '' ? '' : ' '}<${prettyCaller}>`
  }

  if (line === '') {
    return undefined
  } else {
    return line
  }
}
