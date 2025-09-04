'use strict'

/**
 * Listens for an event on an object and resolves a promise when the event is emitted.
 * @param {Object} emitter - The object to listen to.
 * @param {string} event - The name of the event to listen for.
 * @param {Function} fn - The function to call when the event is emitted.
 * @returns {Promise} A promise that resolves when the event is emitted.
 */
function once (emitter, event, fn) {
  return new Promise(resolve => {
    emitter.on(event, (...args) => {
      fn(...args)
      resolve()
    })
  })
}

module.exports = { once }
