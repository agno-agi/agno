"use strict";
exports.se = void 0;
var _index = require("./se/_lib/formatDistance.js");
var _index2 = require("./se/_lib/formatLong.js");
var _index3 = require("./se/_lib/formatRelative.js");
var _index4 = require("./se/_lib/localize.js");
var _index5 = require("./se/_lib/match.js");

/**
 * @category Locales
 * @summary Northern Sámi locale.
 * @language Northern Sámi
 * @iso-639-2 sme
 * @author Audun Rundberg [@audunru](https://github.com/audunru)
 */
const se = (exports.se = {
  code: "se",
  formatDistance: _index.formatDistance,
  formatLong: _index2.formatLong,
  formatRelative: _index3.formatRelative,
  localize: _index4.localize,
  match: _index5.match,
  options: {
    weekStartsOn: 1 /* Monday */,
    firstWeekContainsDate: 4,
  },
});
