function ownKeys(e, r) {var t = Object.keys(e);if (Object.getOwnPropertySymbols) {var o = Object.getOwnPropertySymbols(e);r && (o = o.filter(function (r) {return Object.getOwnPropertyDescriptor(e, r).enumerable;})), t.push.apply(t, o);}return t;}function _objectSpread(e) {for (var r = 1; r < arguments.length; r++) {var t = null != arguments[r] ? arguments[r] : {};r % 2 ? ownKeys(Object(t), !0).forEach(function (r) {_defineProperty(e, r, t[r]);}) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) {Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r));});}return e;}function _createForOfIteratorHelper(o, allowArrayLike) {var it = typeof Symbol !== "undefined" && o[Symbol.iterator] || o["@@iterator"];if (!it) {if (Array.isArray(o) || (it = _unsupportedIterableToArray(o)) || allowArrayLike && o && typeof o.length === "number") {if (it) o = it;var i = 0;var F = function F() {};return { s: F, n: function n() {if (i >= o.length) return { done: true };return { done: false, value: o[i++] };}, e: function e(_e) {throw _e;}, f: F };}throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");}var normalCompletion = true,didErr = false,err;return { s: function s() {it = it.call(o);}, n: function n() {var step = it.next();normalCompletion = step.done;return step;}, e: function e(_e2) {didErr = true;err = _e2;}, f: function f() {try {if (!normalCompletion && it.return != null) it.return();} finally {if (didErr) throw err;}} };}function _callSuper(t, o, e) {return o = _getPrototypeOf(o), _possibleConstructorReturn(t, _isNativeReflectConstruct() ? Reflect.construct(o, e || [], _getPrototypeOf(t).constructor) : o.apply(t, e));}function _possibleConstructorReturn(self, call) {if (call && (_typeof(call) === "object" || typeof call === "function")) {return call;} else if (call !== void 0) {throw new TypeError("Derived constructors may only return object or undefined");}return _assertThisInitialized(self);}function _assertThisInitialized(self) {if (self === void 0) {throw new ReferenceError("this hasn't been initialised - super() hasn't been called");}return self;}function _isNativeReflectConstruct() {try {var t = !Boolean.prototype.valueOf.call(Reflect.construct(Boolean, [], function () {}));} catch (t) {}return (_isNativeReflectConstruct = function _isNativeReflectConstruct() {return !!t;})();}function _getPrototypeOf(o) {_getPrototypeOf = Object.setPrototypeOf ? Object.getPrototypeOf.bind() : function _getPrototypeOf(o) {return o.__proto__ || Object.getPrototypeOf(o);};return _getPrototypeOf(o);}function _inherits(subClass, superClass) {if (typeof superClass !== "function" && superClass !== null) {throw new TypeError("Super expression must either be null or a function");}subClass.prototype = Object.create(superClass && superClass.prototype, { constructor: { value: subClass, writable: true, configurable: true } });Object.defineProperty(subClass, "prototype", { writable: false });if (superClass) _setPrototypeOf(subClass, superClass);}function _setPrototypeOf(o, p) {_setPrototypeOf = Object.setPrototypeOf ? Object.setPrototypeOf.bind() : function _setPrototypeOf(o, p) {o.__proto__ = p;return o;};return _setPrototypeOf(o, p);}function _classCallCheck(instance, Constructor) {if (!(instance instanceof Constructor)) {throw new TypeError("Cannot call a class as a function");}}function _defineProperties(target, props) {for (var i = 0; i < props.length; i++) {var descriptor = props[i];descriptor.enumerable = descriptor.enumerable || false;descriptor.configurable = true;if ("value" in descriptor) descriptor.writable = true;Object.defineProperty(target, _toPropertyKey(descriptor.key), descriptor);}}function _createClass(Constructor, protoProps, staticProps) {if (protoProps) _defineProperties(Constructor.prototype, protoProps);if (staticProps) _defineProperties(Constructor, staticProps);Object.defineProperty(Constructor, "prototype", { writable: false });return Constructor;}function _defineProperty(obj, key, value) {key = _toPropertyKey(key);if (key in obj) {Object.defineProperty(obj, key, { value: value, enumerable: true, configurable: true, writable: true });} else {obj[key] = value;}return obj;}function _toPropertyKey(t) {var i = _toPrimitive(t, "string");return "symbol" == _typeof(i) ? i : String(i);}function _toPrimitive(t, r) {if ("object" != _typeof(t) || !t) return t;var e = t[Symbol.toPrimitive];if (void 0 !== e) {var i = e.call(t, r || "default");if ("object" != _typeof(i)) return i;throw new TypeError("@@toPrimitive must return a primitive value.");}return ("string" === r ? String : Number)(t);}function _slicedToArray(arr, i) {return _arrayWithHoles(arr) || _iterableToArrayLimit(arr, i) || _unsupportedIterableToArray(arr, i) || _nonIterableRest();}function _nonIterableRest() {throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");}function _unsupportedIterableToArray(o, minLen) {if (!o) return;if (typeof o === "string") return _arrayLikeToArray(o, minLen);var n = Object.prototype.toString.call(o).slice(8, -1);if (n === "Object" && o.constructor) n = o.constructor.name;if (n === "Map" || n === "Set") return Array.from(o);if (n === "Arguments" || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n)) return _arrayLikeToArray(o, minLen);}function _arrayLikeToArray(arr, len) {if (len == null || len > arr.length) len = arr.length;for (var i = 0, arr2 = new Array(len); i < len; i++) arr2[i] = arr[i];return arr2;}function _iterableToArrayLimit(r, l) {var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"];if (null != t) {var e,n,i,u,a = [],f = !0,o = !1;try {if (i = (t = t.call(r)).next, 0 === l) {if (Object(t) !== t) return;f = !1;} else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0);} catch (r) {o = !0, n = r;} finally {try {if (!f && null != t.return && (u = t.return(), Object(u) !== u)) return;} finally {if (o) throw n;}}return a;}}function _arrayWithHoles(arr) {if (Array.isArray(arr)) return arr;}function _typeof(o) {"@babel/helpers - typeof";return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) {return typeof o;} : function (o) {return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o;}, _typeof(o);}(function () {var __defProp = Object.defineProperty;
  var __export = function __export(target, all) {
    for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: function set(newValue) {return all[name] = function () {return newValue;};}
    });
  };

  // lib/index.mjs
  var exports_lib = {};
  __export(exports_lib, {
    yearsToQuarters: function yearsToQuarters() {
      {
        return _yearsToQuarters;
      }
    },
    yearsToMonths: function yearsToMonths() {
      {
        return _yearsToMonths;
      }
    },
    yearsToDays: function yearsToDays() {
      {
        return _yearsToDays;
      }
    },
    weeksToDays: function weeksToDays() {
      {
        return _weeksToDays;
      }
    },
    transpose: function transpose() {
      {
        return _transpose;
      }
    },
    toDate: function toDate() {
      {
        return _toDate;
      }
    },
    subYears: function subYears() {
      {
        return _subYears;
      }
    },
    subWeeks: function subWeeks() {
      {
        return _subWeeks;
      }
    },
    subSeconds: function subSeconds() {
      {
        return _subSeconds;
      }
    },
    subQuarters: function subQuarters() {
      {
        return _subQuarters;
      }
    },
    subMonths: function subMonths() {
      {
        return _subMonths;
      }
    },
    subMinutes: function subMinutes() {
      {
        return _subMinutes;
      }
    },
    subMilliseconds: function subMilliseconds() {
      {
        return _subMilliseconds;
      }
    },
    subISOWeekYears: function subISOWeekYears() {
      {
        return _subISOWeekYears;
      }
    },
    subHours: function subHours() {
      {
        return _subHours;
      }
    },
    subDays: function subDays() {
      {
        return _subDays;
      }
    },
    subBusinessDays: function subBusinessDays() {
      {
        return _subBusinessDays;
      }
    },
    sub: function sub() {
      {
        return _sub;
      }
    },
    startOfYesterday: function startOfYesterday() {
      {
        return _startOfYesterday;
      }
    },
    startOfYear: function startOfYear() {
      {
        return _startOfYear;
      }
    },
    startOfWeekYear: function startOfWeekYear() {
      {
        return _startOfWeekYear;
      }
    },
    startOfWeek: function startOfWeek() {
      {
        return _startOfWeek;
      }
    },
    startOfTomorrow: function startOfTomorrow() {
      {
        return _startOfTomorrow;
      }
    },
    startOfToday: function startOfToday() {
      {
        return _startOfToday;
      }
    },
    startOfSecond: function startOfSecond() {
      {
        return _startOfSecond;
      }
    },
    startOfQuarter: function startOfQuarter() {
      {
        return _startOfQuarter;
      }
    },
    startOfMonth: function startOfMonth() {
      {
        return _startOfMonth;
      }
    },
    startOfMinute: function startOfMinute() {
      {
        return _startOfMinute;
      }
    },
    startOfISOWeekYear: function startOfISOWeekYear() {
      {
        return _startOfISOWeekYear;
      }
    },
    startOfISOWeek: function startOfISOWeek() {
      {
        return _startOfISOWeek;
      }
    },
    startOfHour: function startOfHour() {
      {
        return _startOfHour;
      }
    },
    startOfDecade: function startOfDecade() {
      {
        return _startOfDecade;
      }
    },
    startOfDay: function startOfDay() {
      {
        return _startOfDay;
      }
    },
    setYear: function setYear() {
      {
        return _setYear;
      }
    },
    setWeekYear: function setWeekYear() {
      {
        return _setWeekYear;
      }
    },
    setWeek: function setWeek() {
      {
        return _setWeek;
      }
    },
    setSeconds: function setSeconds() {
      {
        return _setSeconds;
      }
    },
    setQuarter: function setQuarter() {
      {
        return _setQuarter;
      }
    },
    setMonth: function setMonth() {
      {
        return _setMonth;
      }
    },
    setMinutes: function setMinutes() {
      {
        return _setMinutes;
      }
    },
    setMilliseconds: function setMilliseconds() {
      {
        return _setMilliseconds;
      }
    },
    setISOWeekYear: function setISOWeekYear() {
      {
        return _setISOWeekYear;
      }
    },
    setISOWeek: function setISOWeek() {
      {
        return _setISOWeek;
      }
    },
    setISODay: function setISODay() {
      {
        return _setISODay;
      }
    },
    setHours: function setHours() {
      {
        return _setHours;
      }
    },
    setDefaultOptions: function setDefaultOptions() {
      {
        return setDefaultOptions2;
      }
    },
    setDayOfYear: function setDayOfYear() {
      {
        return _setDayOfYear;
      }
    },
    setDay: function setDay() {
      {
        return _setDay;
      }
    },
    setDate: function setDate() {
      {
        return _setDate;
      }
    },
    set: function set() {
      {
        return _set;
      }
    },
    secondsToMinutes: function secondsToMinutes() {
      {
        return _secondsToMinutes;
      }
    },
    secondsToMilliseconds: function secondsToMilliseconds() {
      {
        return _secondsToMilliseconds;
      }
    },
    secondsToHours: function secondsToHours() {
      {
        return _secondsToHours;
      }
    },
    roundToNearestMinutes: function roundToNearestMinutes() {
      {
        return _roundToNearestMinutes;
      }
    },
    roundToNearestHours: function roundToNearestHours() {
      {
        return _roundToNearestHours;
      }
    },
    quartersToYears: function quartersToYears() {
      {
        return _quartersToYears;
      }
    },
    quartersToMonths: function quartersToMonths() {
      {
        return _quartersToMonths;
      }
    },
    previousWednesday: function previousWednesday() {
      {
        return _previousWednesday;
      }
    },
    previousTuesday: function previousTuesday() {
      {
        return _previousTuesday;
      }
    },
    previousThursday: function previousThursday() {
      {
        return _previousThursday;
      }
    },
    previousSunday: function previousSunday() {
      {
        return _previousSunday;
      }
    },
    previousSaturday: function previousSaturday() {
      {
        return _previousSaturday;
      }
    },
    previousMonday: function previousMonday() {
      {
        return _previousMonday;
      }
    },
    previousFriday: function previousFriday() {
      {
        return _previousFriday;
      }
    },
    previousDay: function previousDay() {
      {
        return _previousDay;
      }
    },
    parsers: function parsers() {
      {
        return _parsers;
      }
    },
    parseJSON: function parseJSON() {
      {
        return _parseJSON;
      }
    },
    parseISO: function parseISO() {
      {
        return _parseISO;
      }
    },
    parse: function parse() {
      {
        return _parse;
      }
    },
    nextWednesday: function nextWednesday() {
      {
        return _nextWednesday;
      }
    },
    nextTuesday: function nextTuesday() {
      {
        return _nextTuesday;
      }
    },
    nextThursday: function nextThursday() {
      {
        return _nextThursday;
      }
    },
    nextSunday: function nextSunday() {
      {
        return _nextSunday;
      }
    },
    nextSaturday: function nextSaturday() {
      {
        return _nextSaturday;
      }
    },
    nextMonday: function nextMonday() {
      {
        return _nextMonday;
      }
    },
    nextFriday: function nextFriday() {
      {
        return _nextFriday;
      }
    },
    nextDay: function nextDay() {
      {
        return _nextDay;
      }
    },
    monthsToYears: function monthsToYears() {
      {
        return _monthsToYears;
      }
    },
    monthsToQuarters: function monthsToQuarters() {
      {
        return _monthsToQuarters;
      }
    },
    minutesToSeconds: function minutesToSeconds() {
      {
        return _minutesToSeconds;
      }
    },
    minutesToMilliseconds: function minutesToMilliseconds() {
      {
        return _minutesToMilliseconds;
      }
    },
    minutesToHours: function minutesToHours() {
      {
        return _minutesToHours;
      }
    },
    min: function min() {
      {
        return _min;
      }
    },
    millisecondsToSeconds: function millisecondsToSeconds() {
      {
        return _millisecondsToSeconds;
      }
    },
    millisecondsToMinutes: function millisecondsToMinutes() {
      {
        return _millisecondsToMinutes;
      }
    },
    millisecondsToHours: function millisecondsToHours() {
      {
        return _millisecondsToHours;
      }
    },
    milliseconds: function milliseconds() {
      {
        return _milliseconds;
      }
    },
    max: function max() {
      {
        return _max;
      }
    },
    longFormatters: function longFormatters() {
      {
        return _longFormatters;
      }
    },
    lightFormatters: function lightFormatters() {
      {
        return _lightFormatters;
      }
    },
    lightFormat: function lightFormat() {
      {
        return _lightFormat;
      }
    },
    lastDayOfYear: function lastDayOfYear() {
      {
        return _lastDayOfYear;
      }
    },
    lastDayOfWeek: function lastDayOfWeek() {
      {
        return _lastDayOfWeek;
      }
    },
    lastDayOfQuarter: function lastDayOfQuarter() {
      {
        return _lastDayOfQuarter;
      }
    },
    lastDayOfMonth: function lastDayOfMonth() {
      {
        return _lastDayOfMonth;
      }
    },
    lastDayOfISOWeekYear: function lastDayOfISOWeekYear() {
      {
        return _lastDayOfISOWeekYear;
      }
    },
    lastDayOfISOWeek: function lastDayOfISOWeek() {
      {
        return _lastDayOfISOWeek;
      }
    },
    lastDayOfDecade: function lastDayOfDecade() {
      {
        return _lastDayOfDecade;
      }
    },
    isYesterday: function isYesterday() {
      {
        return _isYesterday;
      }
    },
    isWithinInterval: function isWithinInterval() {
      {
        return _isWithinInterval;
      }
    },
    isWeekend: function isWeekend() {
      {
        return _isWeekend;
      }
    },
    isWednesday: function isWednesday() {
      {
        return _isWednesday;
      }
    },
    isValid: function isValid() {
      {
        return _isValid;
      }
    },
    isTuesday: function isTuesday() {
      {
        return _isTuesday;
      }
    },
    isTomorrow: function isTomorrow() {
      {
        return _isTomorrow;
      }
    },
    isToday: function isToday() {
      {
        return _isToday;
      }
    },
    isThursday: function isThursday() {
      {
        return _isThursday;
      }
    },
    isThisYear: function isThisYear() {
      {
        return _isThisYear;
      }
    },
    isThisWeek: function isThisWeek() {
      {
        return _isThisWeek;
      }
    },
    isThisSecond: function isThisSecond() {
      {
        return _isThisSecond;
      }
    },
    isThisQuarter: function isThisQuarter() {
      {
        return _isThisQuarter;
      }
    },
    isThisMonth: function isThisMonth() {
      {
        return _isThisMonth;
      }
    },
    isThisMinute: function isThisMinute() {
      {
        return _isThisMinute;
      }
    },
    isThisISOWeek: function isThisISOWeek() {
      {
        return _isThisISOWeek;
      }
    },
    isThisHour: function isThisHour() {
      {
        return _isThisHour;
      }
    },
    isSunday: function isSunday() {
      {
        return _isSunday;
      }
    },
    isSaturday: function isSaturday() {
      {
        return _isSaturday;
      }
    },
    isSameYear: function isSameYear() {
      {
        return _isSameYear;
      }
    },
    isSameWeek: function isSameWeek() {
      {
        return _isSameWeek;
      }
    },
    isSameSecond: function isSameSecond() {
      {
        return _isSameSecond;
      }
    },
    isSameQuarter: function isSameQuarter() {
      {
        return _isSameQuarter;
      }
    },
    isSameMonth: function isSameMonth() {
      {
        return _isSameMonth;
      }
    },
    isSameMinute: function isSameMinute() {
      {
        return _isSameMinute;
      }
    },
    isSameISOWeekYear: function isSameISOWeekYear() {
      {
        return _isSameISOWeekYear;
      }
    },
    isSameISOWeek: function isSameISOWeek() {
      {
        return _isSameISOWeek;
      }
    },
    isSameHour: function isSameHour() {
      {
        return _isSameHour;
      }
    },
    isSameDay: function isSameDay() {
      {
        return _isSameDay;
      }
    },
    isPast: function isPast() {
      {
        return _isPast;
      }
    },
    isMonday: function isMonday() {
      {
        return _isMonday;
      }
    },
    isMatch: function isMatch() {
      {
        return _isMatch;
      }
    },
    isLeapYear: function isLeapYear() {
      {
        return _isLeapYear;
      }
    },
    isLastDayOfMonth: function isLastDayOfMonth() {
      {
        return _isLastDayOfMonth;
      }
    },
    isFuture: function isFuture() {
      {
        return _isFuture;
      }
    },
    isFriday: function isFriday() {
      {
        return _isFriday;
      }
    },
    isFirstDayOfMonth: function isFirstDayOfMonth() {
      {
        return _isFirstDayOfMonth;
      }
    },
    isExists: function isExists() {
      {
        return _isExists;
      }
    },
    isEqual: function isEqual() {
      {
        return _isEqual;
      }
    },
    isDate: function isDate() {
      {
        return _isDate;
      }
    },
    isBefore: function isBefore() {
      {
        return _isBefore;
      }
    },
    isAfter: function isAfter() {
      {
        return _isAfter;
      }
    },
    intlFormatDistance: function intlFormatDistance() {
      {
        return _intlFormatDistance;
      }
    },
    intlFormat: function intlFormat() {
      {
        return _intlFormat;
      }
    },
    intervalToDuration: function intervalToDuration() {
      {
        return _intervalToDuration;
      }
    },
    interval: function interval() {
      {
        return _interval;
      }
    },
    hoursToSeconds: function hoursToSeconds() {
      {
        return _hoursToSeconds;
      }
    },
    hoursToMinutes: function hoursToMinutes() {
      {
        return _hoursToMinutes;
      }
    },
    hoursToMilliseconds: function hoursToMilliseconds() {
      {
        return _hoursToMilliseconds;
      }
    },
    getYear: function getYear() {
      {
        return _getYear;
      }
    },
    getWeeksInMonth: function getWeeksInMonth() {
      {
        return _getWeeksInMonth;
      }
    },
    getWeekYear: function getWeekYear() {
      {
        return _getWeekYear;
      }
    },
    getWeekOfMonth: function getWeekOfMonth() {
      {
        return _getWeekOfMonth;
      }
    },
    getWeek: function getWeek() {
      {
        return _getWeek;
      }
    },
    getUnixTime: function getUnixTime() {
      {
        return _getUnixTime;
      }
    },
    getTime: function getTime() {
      {
        return _getTime;
      }
    },
    getSeconds: function getSeconds() {
      {
        return _getSeconds;
      }
    },
    getQuarter: function getQuarter() {
      {
        return _getQuarter;
      }
    },
    getOverlappingDaysInIntervals: function getOverlappingDaysInIntervals() {
      {
        return _getOverlappingDaysInIntervals;
      }
    },
    getMonth: function getMonth() {
      {
        return _getMonth;
      }
    },
    getMinutes: function getMinutes() {
      {
        return _getMinutes;
      }
    },
    getMilliseconds: function getMilliseconds() {
      {
        return _getMilliseconds;
      }
    },
    getISOWeeksInYear: function getISOWeeksInYear() {
      {
        return _getISOWeeksInYear;
      }
    },
    getISOWeekYear: function getISOWeekYear() {
      {
        return _getISOWeekYear;
      }
    },
    getISOWeek: function getISOWeek() {
      {
        return _getISOWeek;
      }
    },
    getISODay: function getISODay() {
      {
        return _getISODay;
      }
    },
    getHours: function getHours() {
      {
        return _getHours;
      }
    },
    getDefaultOptions: function getDefaultOptions() {
      {
        return getDefaultOptions2;
      }
    },
    getDecade: function getDecade() {
      {
        return _getDecade;
      }
    },
    getDaysInYear: function getDaysInYear() {
      {
        return _getDaysInYear;
      }
    },
    getDaysInMonth: function getDaysInMonth() {
      {
        return _getDaysInMonth;
      }
    },
    getDayOfYear: function getDayOfYear() {
      {
        return _getDayOfYear;
      }
    },
    getDay: function getDay() {
      {
        return _getDay;
      }
    },
    getDate: function getDate() {
      {
        return _getDate;
      }
    },
    fromUnixTime: function fromUnixTime() {
      {
        return _fromUnixTime;
      }
    },
    formatters: function formatters() {
      {
        return _formatters;
      }
    },
    formatRelative: function formatRelative() {
      {
        return formatRelative3;
      }
    },
    formatRFC7231: function formatRFC7231() {
      {
        return _formatRFC;
      }
    },
    formatRFC3339: function formatRFC3339() {
      {
        return _formatRFC2;
      }
    },
    formatISODuration: function formatISODuration() {
      {
        return _formatISODuration;
      }
    },
    formatISO9075: function formatISO9075() {
      {
        return _formatISO;
      }
    },
    formatISO: function formatISO() {
      {
        return _formatISO2;
      }
    },
    formatDuration: function formatDuration() {
      {
        return _formatDuration;
      }
    },
    formatDistanceToNowStrict: function formatDistanceToNowStrict() {
      {
        return _formatDistanceToNowStrict;
      }
    },
    formatDistanceToNow: function formatDistanceToNow() {
      {
        return _formatDistanceToNow;
      }
    },
    formatDistanceStrict: function formatDistanceStrict() {
      {
        return _formatDistanceStrict;
      }
    },
    formatDistance: function formatDistance() {
      {
        return formatDistance3;
      }
    },
    formatDate: function formatDate() {
      {
        return _format;
      }
    },
    format: function format() {
      {
        return _format;
      }
    },
    endOfYesterday: function endOfYesterday() {
      {
        return _endOfYesterday;
      }
    },
    endOfYear: function endOfYear() {
      {
        return _endOfYear;
      }
    },
    endOfWeek: function endOfWeek() {
      {
        return _endOfWeek;
      }
    },
    endOfTomorrow: function endOfTomorrow() {
      {
        return _endOfTomorrow;
      }
    },
    endOfToday: function endOfToday() {
      {
        return _endOfToday;
      }
    },
    endOfSecond: function endOfSecond() {
      {
        return _endOfSecond;
      }
    },
    endOfQuarter: function endOfQuarter() {
      {
        return _endOfQuarter;
      }
    },
    endOfMonth: function endOfMonth() {
      {
        return _endOfMonth;
      }
    },
    endOfMinute: function endOfMinute() {
      {
        return _endOfMinute;
      }
    },
    endOfISOWeekYear: function endOfISOWeekYear() {
      {
        return _endOfISOWeekYear;
      }
    },
    endOfISOWeek: function endOfISOWeek() {
      {
        return _endOfISOWeek;
      }
    },
    endOfHour: function endOfHour() {
      {
        return _endOfHour;
      }
    },
    endOfDecade: function endOfDecade() {
      {
        return _endOfDecade;
      }
    },
    endOfDay: function endOfDay() {
      {
        return _endOfDay;
      }
    },
    eachYearOfInterval: function eachYearOfInterval() {
      {
        return _eachYearOfInterval;
      }
    },
    eachWeekendOfYear: function eachWeekendOfYear() {
      {
        return _eachWeekendOfYear;
      }
    },
    eachWeekendOfMonth: function eachWeekendOfMonth() {
      {
        return _eachWeekendOfMonth;
      }
    },
    eachWeekendOfInterval: function eachWeekendOfInterval() {
      {
        return _eachWeekendOfInterval;
      }
    },
    eachWeekOfInterval: function eachWeekOfInterval() {
      {
        return _eachWeekOfInterval;
      }
    },
    eachQuarterOfInterval: function eachQuarterOfInterval() {
      {
        return _eachQuarterOfInterval;
      }
    },
    eachMonthOfInterval: function eachMonthOfInterval() {
      {
        return _eachMonthOfInterval;
      }
    },
    eachMinuteOfInterval: function eachMinuteOfInterval() {
      {
        return _eachMinuteOfInterval;
      }
    },
    eachHourOfInterval: function eachHourOfInterval() {
      {
        return _eachHourOfInterval;
      }
    },
    eachDayOfInterval: function eachDayOfInterval() {
      {
        return _eachDayOfInterval;
      }
    },
    differenceInYears: function differenceInYears() {
      {
        return _differenceInYears;
      }
    },
    differenceInWeeks: function differenceInWeeks() {
      {
        return _differenceInWeeks;
      }
    },
    differenceInSeconds: function differenceInSeconds() {
      {
        return _differenceInSeconds;
      }
    },
    differenceInQuarters: function differenceInQuarters() {
      {
        return _differenceInQuarters;
      }
    },
    differenceInMonths: function differenceInMonths() {
      {
        return _differenceInMonths;
      }
    },
    differenceInMinutes: function differenceInMinutes() {
      {
        return _differenceInMinutes;
      }
    },
    differenceInMilliseconds: function differenceInMilliseconds() {
      {
        return _differenceInMilliseconds;
      }
    },
    differenceInISOWeekYears: function differenceInISOWeekYears() {
      {
        return _differenceInISOWeekYears;
      }
    },
    differenceInHours: function differenceInHours() {
      {
        return _differenceInHours;
      }
    },
    differenceInDays: function differenceInDays() {
      {
        return _differenceInDays;
      }
    },
    differenceInCalendarYears: function differenceInCalendarYears() {
      {
        return _differenceInCalendarYears;
      }
    },
    differenceInCalendarWeeks: function differenceInCalendarWeeks() {
      {
        return _differenceInCalendarWeeks;
      }
    },
    differenceInCalendarQuarters: function differenceInCalendarQuarters() {
      {
        return _differenceInCalendarQuarters;
      }
    },
    differenceInCalendarMonths: function differenceInCalendarMonths() {
      {
        return _differenceInCalendarMonths;
      }
    },
    differenceInCalendarISOWeeks: function differenceInCalendarISOWeeks() {
      {
        return _differenceInCalendarISOWeeks;
      }
    },
    differenceInCalendarISOWeekYears: function differenceInCalendarISOWeekYears() {
      {
        return _differenceInCalendarISOWeekYears;
      }
    },
    differenceInCalendarDays: function differenceInCalendarDays() {
      {
        return _differenceInCalendarDays;
      }
    },
    differenceInBusinessDays: function differenceInBusinessDays() {
      {
        return _differenceInBusinessDays;
      }
    },
    daysToWeeks: function daysToWeeks() {
      {
        return _daysToWeeks;
      }
    },
    constructNow: function constructNow() {
      {
        return _constructNow;
      }
    },
    constructFrom: function constructFrom() {
      {
        return _constructFrom;
      }
    },
    compareDesc: function compareDesc() {
      {
        return _compareDesc;
      }
    },
    compareAsc: function compareAsc() {
      {
        return _compareAsc;
      }
    },
    closestTo: function closestTo() {
      {
        return _closestTo;
      }
    },
    closestIndexTo: function closestIndexTo() {
      {
        return _closestIndexTo;
      }
    },
    clamp: function clamp() {
      {
        return _clamp;
      }
    },
    areIntervalsOverlapping: function areIntervalsOverlapping() {
      {
        return _areIntervalsOverlapping;
      }
    },
    addYears: function addYears() {
      {
        return _addYears;
      }
    },
    addWeeks: function addWeeks() {
      {
        return _addWeeks;
      }
    },
    addSeconds: function addSeconds() {
      {
        return _addSeconds;
      }
    },
    addQuarters: function addQuarters() {
      {
        return _addQuarters;
      }
    },
    addMonths: function addMonths() {
      {
        return _addMonths;
      }
    },
    addMinutes: function addMinutes() {
      {
        return _addMinutes;
      }
    },
    addMilliseconds: function addMilliseconds() {
      {
        return _addMilliseconds;
      }
    },
    addISOWeekYears: function addISOWeekYears() {
      {
        return _addISOWeekYears;
      }
    },
    addHours: function addHours() {
      {
        return _addHours;
      }
    },
    addDays: function addDays() {
      {
        return _addDays;
      }
    },
    addBusinessDays: function addBusinessDays() {
      {
        return _addBusinessDays;
      }
    },
    add: function add() {
      {
        return _add;
      }
    }
  });

  // lib/toDate.mjs
  function _toDate(argument) {
    var argStr = Object.prototype.toString.call(argument);
    if (argument instanceof Date || _typeof(argument) === "object" && argStr === "[object Date]") {
      return new argument.constructor(+argument);
    } else if (typeof argument === "number" || argStr === "[object Number]" || typeof argument === "string" || argStr === "[object String]") {
      return new Date(argument);
    } else {
      return new Date(NaN);
    }
  }

  // lib/constructFrom.mjs
  function _constructFrom(date, value) {
    if (date instanceof Date) {
      return new date.constructor(value);
    } else {
      return new Date(value);
    }
  }

  // lib/addDays.mjs
  function _addDays(date, amount) {
    var _date = _toDate(date);
    if (isNaN(amount))
    return _constructFrom(date, NaN);
    if (!amount) {
      return _date;
    }
    _date.setDate(_date.getDate() + amount);
    return _date;
  }

  // lib/addMonths.mjs
  function _addMonths(date, amount) {
    var _date = _toDate(date);
    if (isNaN(amount))
    return _constructFrom(date, NaN);
    if (!amount) {
      return _date;
    }
    var dayOfMonth = _date.getDate();
    var endOfDesiredMonth = _constructFrom(date, _date.getTime());
    endOfDesiredMonth.setMonth(_date.getMonth() + amount + 1, 0);
    var daysInMonth = endOfDesiredMonth.getDate();
    if (dayOfMonth >= daysInMonth) {
      return endOfDesiredMonth;
    } else {
      _date.setFullYear(endOfDesiredMonth.getFullYear(), endOfDesiredMonth.getMonth(), dayOfMonth);
      return _date;
    }
  }

  // lib/add.mjs
  function _add(date, duration) {
    var _duration$years =







      duration.years,years = _duration$years === void 0 ? 0 : _duration$years,_duration$months = duration.months,months = _duration$months === void 0 ? 0 : _duration$months,_duration$weeks = duration.weeks,weeks = _duration$weeks === void 0 ? 0 : _duration$weeks,_duration$days = duration.days,days = _duration$days === void 0 ? 0 : _duration$days,_duration$hours = duration.hours,hours = _duration$hours === void 0 ? 0 : _duration$hours,_duration$minutes = duration.minutes,minutes = _duration$minutes === void 0 ? 0 : _duration$minutes,_duration$seconds = duration.seconds,seconds = _duration$seconds === void 0 ? 0 : _duration$seconds;
    var _date = _toDate(date);
    var dateWithMonths = months || years ? _addMonths(_date, months + years * 12) : _date;
    var dateWithDays = days || weeks ? _addDays(dateWithMonths, days + weeks * 7) : dateWithMonths;
    var minutesToAdd = minutes + hours * 60;
    var secondsToAdd = seconds + minutesToAdd * 60;
    var msToAdd = secondsToAdd * 1000;
    var finalDate = _constructFrom(date, dateWithDays.getTime() + msToAdd);
    return finalDate;
  }
  // lib/isSaturday.mjs
  function _isSaturday(date) {
    return _toDate(date).getDay() === 6;
  }

  // lib/isSunday.mjs
  function _isSunday(date) {
    return _toDate(date).getDay() === 0;
  }

  // lib/isWeekend.mjs
  function _isWeekend(date) {
    var day = _toDate(date).getDay();
    return day === 0 || day === 6;
  }

  // lib/addBusinessDays.mjs
  function _addBusinessDays(date, amount) {
    var _date = _toDate(date);
    var startedOnWeekend = _isWeekend(_date);
    if (isNaN(amount))
    return _constructFrom(date, NaN);
    var hours = _date.getHours();
    var sign = amount < 0 ? -1 : 1;
    var fullWeeks = Math.trunc(amount / 5);
    _date.setDate(_date.getDate() + fullWeeks * 7);
    var restDays = Math.abs(amount % 5);
    while (restDays > 0) {
      _date.setDate(_date.getDate() + sign);
      if (!_isWeekend(_date))
      restDays -= 1;
    }
    if (startedOnWeekend && _isWeekend(_date) && amount !== 0) {
      if (_isSaturday(_date))
      _date.setDate(_date.getDate() + (sign < 0 ? 2 : -1));
      if (_isSunday(_date))
      _date.setDate(_date.getDate() + (sign < 0 ? 1 : -2));
    }
    _date.setHours(hours);
    return _date;
  }
  // lib/addMilliseconds.mjs
  function _addMilliseconds(date, amount) {
    var timestamp = +_toDate(date);
    return _constructFrom(date, timestamp + amount);
  }

  // lib/constants.mjs
  var daysInWeek = 7;
  var daysInYear = 365.2425;
  var maxTime = Math.pow(10, 8) * 24 * 60 * 60 * 1000;
  var minTime = -maxTime;
  var millisecondsInWeek = 604800000;
  var millisecondsInDay = 86400000;
  var millisecondsInMinute = 60000;
  var millisecondsInHour = 3600000;
  var millisecondsInSecond = 1000;
  var minutesInYear = 525600;
  var minutesInMonth = 43200;
  var minutesInDay = 1440;
  var minutesInHour = 60;
  var monthsInQuarter = 3;
  var monthsInYear = 12;
  var quartersInYear = 4;
  var secondsInHour = 3600;
  var secondsInMinute = 60;
  var secondsInDay = secondsInHour * 24;
  var secondsInWeek = secondsInDay * 7;
  var secondsInYear = secondsInDay * daysInYear;
  var secondsInMonth = secondsInYear / 12;
  var secondsInQuarter = secondsInMonth * 3;

  // lib/addHours.mjs
  function _addHours(date, amount) {
    return _addMilliseconds(date, amount * millisecondsInHour);
  }
  // lib/_lib/defaultOptions.mjs
  function getDefaultOptions() {
    return defaultOptions;
  }
  function setDefaultOptions(newOptions) {
    defaultOptions = newOptions;
  }
  var defaultOptions = {};

  // lib/startOfWeek.mjs
  function _startOfWeek(date, options) {var _ref, _ref2, _ref3, _options$weekStartsOn, _options$locale, _defaultOptions3$loca;
    var defaultOptions3 = getDefaultOptions();
    var weekStartsOn = (_ref = (_ref2 = (_ref3 = (_options$weekStartsOn = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn !== void 0 ? _options$weekStartsOn : options === null || options === void 0 || (_options$locale = options.locale) === null || _options$locale === void 0 || (_options$locale = _options$locale.options) === null || _options$locale === void 0 ? void 0 : _options$locale.weekStartsOn) !== null && _ref3 !== void 0 ? _ref3 : defaultOptions3.weekStartsOn) !== null && _ref2 !== void 0 ? _ref2 : (_defaultOptions3$loca = defaultOptions3.locale) === null || _defaultOptions3$loca === void 0 || (_defaultOptions3$loca = _defaultOptions3$loca.options) === null || _defaultOptions3$loca === void 0 ? void 0 : _defaultOptions3$loca.weekStartsOn) !== null && _ref !== void 0 ? _ref : 0;
    var _date = _toDate(date);
    var day = _date.getDay();
    var diff = (day < weekStartsOn ? 7 : 0) + day - weekStartsOn;
    _date.setDate(_date.getDate() - diff);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/startOfISOWeek.mjs
  function _startOfISOWeek(date) {
    return _startOfWeek(date, { weekStartsOn: 1 });
  }

  // lib/getISOWeekYear.mjs
  function _getISOWeekYear(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var fourthOfJanuaryOfNextYear = _constructFrom(date, 0);
    fourthOfJanuaryOfNextYear.setFullYear(year + 1, 0, 4);
    fourthOfJanuaryOfNextYear.setHours(0, 0, 0, 0);
    var startOfNextYear = _startOfISOWeek(fourthOfJanuaryOfNextYear);
    var fourthOfJanuaryOfThisYear = _constructFrom(date, 0);
    fourthOfJanuaryOfThisYear.setFullYear(year, 0, 4);
    fourthOfJanuaryOfThisYear.setHours(0, 0, 0, 0);
    var startOfThisYear = _startOfISOWeek(fourthOfJanuaryOfThisYear);
    if (_date.getTime() >= startOfNextYear.getTime()) {
      return year + 1;
    } else if (_date.getTime() >= startOfThisYear.getTime()) {
      return year;
    } else {
      return year - 1;
    }
  }

  // lib/startOfDay.mjs
  function _startOfDay(date) {
    var _date = _toDate(date);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/_lib/getTimezoneOffsetInMilliseconds.mjs
  function getTimezoneOffsetInMilliseconds(date) {
    var _date = _toDate(date);
    var utcDate = new Date(Date.UTC(_date.getFullYear(), _date.getMonth(), _date.getDate(), _date.getHours(), _date.getMinutes(), _date.getSeconds(), _date.getMilliseconds()));
    utcDate.setUTCFullYear(_date.getFullYear());
    return +date - +utcDate;
  }

  // lib/differenceInCalendarDays.mjs
  function _differenceInCalendarDays(dateLeft, dateRight) {
    var startOfDayLeft = _startOfDay(dateLeft);
    var startOfDayRight = _startOfDay(dateRight);
    var timestampLeft = +startOfDayLeft - getTimezoneOffsetInMilliseconds(startOfDayLeft);
    var timestampRight = +startOfDayRight - getTimezoneOffsetInMilliseconds(startOfDayRight);
    return Math.round((timestampLeft - timestampRight) / millisecondsInDay);
  }

  // lib/startOfISOWeekYear.mjs
  function _startOfISOWeekYear(date) {
    var year = _getISOWeekYear(date);
    var fourthOfJanuary = _constructFrom(date, 0);
    fourthOfJanuary.setFullYear(year, 0, 4);
    fourthOfJanuary.setHours(0, 0, 0, 0);
    return _startOfISOWeek(fourthOfJanuary);
  }

  // lib/setISOWeekYear.mjs
  function _setISOWeekYear(date, weekYear) {
    var _date = _toDate(date);
    var diff = _differenceInCalendarDays(_date, _startOfISOWeekYear(_date));
    var fourthOfJanuary = _constructFrom(date, 0);
    fourthOfJanuary.setFullYear(weekYear, 0, 4);
    fourthOfJanuary.setHours(0, 0, 0, 0);
    _date = _startOfISOWeekYear(fourthOfJanuary);
    _date.setDate(_date.getDate() + diff);
    return _date;
  }

  // lib/addISOWeekYears.mjs
  function _addISOWeekYears(date, amount) {
    return _setISOWeekYear(date, _getISOWeekYear(date) + amount);
  }
  // lib/addMinutes.mjs
  function _addMinutes(date, amount) {
    return _addMilliseconds(date, amount * millisecondsInMinute);
  }
  // lib/addQuarters.mjs
  function _addQuarters(date, amount) {
    var months = amount * 3;
    return _addMonths(date, months);
  }
  // lib/addSeconds.mjs
  function _addSeconds(date, amount) {
    return _addMilliseconds(date, amount * 1000);
  }
  // lib/addWeeks.mjs
  function _addWeeks(date, amount) {
    var days = amount * 7;
    return _addDays(date, days);
  }
  // lib/addYears.mjs
  function _addYears(date, amount) {
    return _addMonths(date, amount * 12);
  }
  // lib/areIntervalsOverlapping.mjs
  function _areIntervalsOverlapping(intervalLeft, intervalRight, options) {
    var _sort = [
      +_toDate(intervalLeft.start),
      +_toDate(intervalLeft.end)].
      sort(function (a, b) {return a - b;}),_sort2 = _slicedToArray(_sort, 2),leftStartTime = _sort2[0],leftEndTime = _sort2[1];
    var _sort3 = [
      +_toDate(intervalRight.start),
      +_toDate(intervalRight.end)].
      sort(function (a, b) {return a - b;}),_sort4 = _slicedToArray(_sort3, 2),rightStartTime = _sort4[0],rightEndTime = _sort4[1];
    if (options !== null && options !== void 0 && options.inclusive)
    return leftStartTime <= rightEndTime && rightStartTime <= leftEndTime;
    return leftStartTime < rightEndTime && rightStartTime < leftEndTime;
  }
  // lib/max.mjs
  function _max(dates) {
    var result;
    dates.forEach(function (dirtyDate) {
      var currentDate = _toDate(dirtyDate);
      if (result === undefined || result < currentDate || isNaN(Number(currentDate))) {
        result = currentDate;
      }
    });
    return result || new Date(NaN);
  }

  // lib/min.mjs
  function _min(dates) {
    var result;
    dates.forEach(function (dirtyDate) {
      var date = _toDate(dirtyDate);
      if (!result || result > date || isNaN(+date)) {
        result = date;
      }
    });
    return result || new Date(NaN);
  }

  // lib/clamp.mjs
  function _clamp(date, interval) {
    return _min([_max([date, interval.start]), interval.end]);
  }
  // lib/closestIndexTo.mjs
  function _closestIndexTo(dateToCompare, dates) {
    var date = _toDate(dateToCompare);
    if (isNaN(Number(date)))
    return NaN;
    var timeToCompare = date.getTime();
    var result;
    var minDistance;
    dates.forEach(function (dirtyDate, index) {
      var currentDate = _toDate(dirtyDate);
      if (isNaN(Number(currentDate))) {
        result = NaN;
        minDistance = NaN;
        return;
      }
      var distance = Math.abs(timeToCompare - currentDate.getTime());
      if (result == null || distance < minDistance) {
        result = index;
        minDistance = distance;
      }
    });
    return result;
  }
  // lib/closestTo.mjs
  function _closestTo(dateToCompare, dates) {
    var date = _toDate(dateToCompare);
    if (isNaN(Number(date)))
    return _constructFrom(dateToCompare, NaN);
    var timeToCompare = date.getTime();
    var result;
    var minDistance;
    dates.forEach(function (dirtyDate) {
      var currentDate = _toDate(dirtyDate);
      if (isNaN(Number(currentDate))) {
        result = _constructFrom(dateToCompare, NaN);
        minDistance = NaN;
        return;
      }
      var distance = Math.abs(timeToCompare - currentDate.getTime());
      if (result == null || distance < minDistance) {
        result = currentDate;
        minDistance = distance;
      }
    });
    return result;
  }
  // lib/compareAsc.mjs
  function _compareAsc(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var diff = _dateLeft.getTime() - _dateRight.getTime();
    if (diff < 0) {
      return -1;
    } else if (diff > 0) {
      return 1;
    } else {
      return diff;
    }
  }
  // lib/compareDesc.mjs
  function _compareDesc(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var diff = _dateLeft.getTime() - _dateRight.getTime();
    if (diff > 0) {
      return -1;
    } else if (diff < 0) {
      return 1;
    } else {
      return diff;
    }
  }
  // lib/constructNow.mjs
  function _constructNow(date) {
    return _constructFrom(date, Date.now());
  }
  // lib/daysToWeeks.mjs
  function _daysToWeeks(days) {
    var weeks = days / daysInWeek;
    var result = Math.trunc(weeks);
    return result === 0 ? 0 : result;
  }
  // lib/isSameDay.mjs
  function _isSameDay(dateLeft, dateRight) {
    var dateLeftStartOfDay = _startOfDay(dateLeft);
    var dateRightStartOfDay = _startOfDay(dateRight);
    return +dateLeftStartOfDay === +dateRightStartOfDay;
  }

  // lib/isDate.mjs
  function _isDate(value) {
    return value instanceof Date || _typeof(value) === "object" && Object.prototype.toString.call(value) === "[object Date]";
  }

  // lib/isValid.mjs
  function _isValid(date) {
    if (!_isDate(date) && typeof date !== "number") {
      return false;
    }
    var _date = _toDate(date);
    return !isNaN(Number(_date));
  }

  // lib/differenceInBusinessDays.mjs
  function _differenceInBusinessDays(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    if (!_isValid(_dateLeft) || !_isValid(_dateRight))
    return NaN;
    var calendarDifference = _differenceInCalendarDays(_dateLeft, _dateRight);
    var sign = calendarDifference < 0 ? -1 : 1;
    var weeks = Math.trunc(calendarDifference / 7);
    var result = weeks * 5;
    _dateRight = _addDays(_dateRight, weeks * 7);
    while (!_isSameDay(_dateLeft, _dateRight)) {
      result += _isWeekend(_dateRight) ? 0 : sign;
      _dateRight = _addDays(_dateRight, sign);
    }
    return result === 0 ? 0 : result;
  }
  // lib/differenceInCalendarISOWeekYears.mjs
  function _differenceInCalendarISOWeekYears(dateLeft, dateRight) {
    return _getISOWeekYear(dateLeft) - _getISOWeekYear(dateRight);
  }
  // lib/differenceInCalendarISOWeeks.mjs
  function _differenceInCalendarISOWeeks(dateLeft, dateRight) {
    var startOfISOWeekLeft = _startOfISOWeek(dateLeft);
    var startOfISOWeekRight = _startOfISOWeek(dateRight);
    var timestampLeft = +startOfISOWeekLeft - getTimezoneOffsetInMilliseconds(startOfISOWeekLeft);
    var timestampRight = +startOfISOWeekRight - getTimezoneOffsetInMilliseconds(startOfISOWeekRight);
    return Math.round((timestampLeft - timestampRight) / millisecondsInWeek);
  }
  // lib/differenceInCalendarMonths.mjs
  function _differenceInCalendarMonths(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var yearDiff = _dateLeft.getFullYear() - _dateRight.getFullYear();
    var monthDiff = _dateLeft.getMonth() - _dateRight.getMonth();
    return yearDiff * 12 + monthDiff;
  }
  // lib/getQuarter.mjs
  function _getQuarter(date) {
    var _date = _toDate(date);
    var quarter = Math.trunc(_date.getMonth() / 3) + 1;
    return quarter;
  }

  // lib/differenceInCalendarQuarters.mjs
  function _differenceInCalendarQuarters(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var yearDiff = _dateLeft.getFullYear() - _dateRight.getFullYear();
    var quarterDiff = _getQuarter(_dateLeft) - _getQuarter(_dateRight);
    return yearDiff * 4 + quarterDiff;
  }
  // lib/differenceInCalendarWeeks.mjs
  function _differenceInCalendarWeeks(dateLeft, dateRight, options) {
    var startOfWeekLeft = _startOfWeek(dateLeft, options);
    var startOfWeekRight = _startOfWeek(dateRight, options);
    var timestampLeft = +startOfWeekLeft - getTimezoneOffsetInMilliseconds(startOfWeekLeft);
    var timestampRight = +startOfWeekRight - getTimezoneOffsetInMilliseconds(startOfWeekRight);
    return Math.round((timestampLeft - timestampRight) / millisecondsInWeek);
  }
  // lib/differenceInCalendarYears.mjs
  function _differenceInCalendarYears(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    return _dateLeft.getFullYear() - _dateRight.getFullYear();
  }
  // lib/differenceInDays.mjs
  function _differenceInDays(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var sign = compareLocalAsc(_dateLeft, _dateRight);
    var difference = Math.abs(_differenceInCalendarDays(_dateLeft, _dateRight));
    _dateLeft.setDate(_dateLeft.getDate() - sign * difference);
    var isLastDayNotFull = Number(compareLocalAsc(_dateLeft, _dateRight) === -sign);
    var result = sign * (difference - isLastDayNotFull);
    return result === 0 ? 0 : result;
  }
  var compareLocalAsc = function compareLocalAsc(dateLeft, dateRight) {
    var diff = dateLeft.getFullYear() - dateRight.getFullYear() || dateLeft.getMonth() - dateRight.getMonth() || dateLeft.getDate() - dateRight.getDate() || dateLeft.getHours() - dateRight.getHours() || dateLeft.getMinutes() - dateRight.getMinutes() || dateLeft.getSeconds() - dateRight.getSeconds() || dateLeft.getMilliseconds() - dateRight.getMilliseconds();
    if (diff < 0) {
      return -1;
    } else if (diff > 0) {
      return 1;
    } else {
      return diff;
    }
  };
  // lib/_lib/getRoundingMethod.mjs
  function getRoundingMethod(method) {
    return function (number) {
      var round = method ? Math[method] : Math.trunc;
      var result = round(number);
      return result === 0 ? 0 : result;
    };
  }

  // lib/differenceInMilliseconds.mjs
  function _differenceInMilliseconds(dateLeft, dateRight) {
    return +_toDate(dateLeft) - +_toDate(dateRight);
  }

  // lib/differenceInHours.mjs
  function _differenceInHours(dateLeft, dateRight, options) {
    var diff = _differenceInMilliseconds(dateLeft, dateRight) / millisecondsInHour;
    return getRoundingMethod(options === null || options === void 0 ? void 0 : options.roundingMethod)(diff);
  }
  // lib/subISOWeekYears.mjs
  function _subISOWeekYears(date, amount) {
    return _addISOWeekYears(date, -amount);
  }

  // lib/differenceInISOWeekYears.mjs
  function _differenceInISOWeekYears(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var sign = _compareAsc(_dateLeft, _dateRight);
    var difference = Math.abs(_differenceInCalendarISOWeekYears(_dateLeft, _dateRight));
    _dateLeft = _subISOWeekYears(_dateLeft, sign * difference);
    var isLastISOWeekYearNotFull = Number(_compareAsc(_dateLeft, _dateRight) === -sign);
    var result = sign * (difference - isLastISOWeekYearNotFull);
    return result === 0 ? 0 : result;
  }
  // lib/differenceInMinutes.mjs
  function _differenceInMinutes(dateLeft, dateRight, options) {
    var diff = _differenceInMilliseconds(dateLeft, dateRight) / millisecondsInMinute;
    return getRoundingMethod(options === null || options === void 0 ? void 0 : options.roundingMethod)(diff);
  }
  // lib/endOfDay.mjs
  function _endOfDay(date) {
    var _date = _toDate(date);
    _date.setHours(23, 59, 59, 999);
    return _date;
  }

  // lib/endOfMonth.mjs
  function _endOfMonth(date) {
    var _date = _toDate(date);
    var month = _date.getMonth();
    _date.setFullYear(_date.getFullYear(), month + 1, 0);
    _date.setHours(23, 59, 59, 999);
    return _date;
  }

  // lib/isLastDayOfMonth.mjs
  function _isLastDayOfMonth(date) {
    var _date = _toDate(date);
    return +_endOfDay(_date) === +_endOfMonth(_date);
  }

  // lib/differenceInMonths.mjs
  function _differenceInMonths(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var sign = _compareAsc(_dateLeft, _dateRight);
    var difference = Math.abs(_differenceInCalendarMonths(_dateLeft, _dateRight));
    var result;
    if (difference < 1) {
      result = 0;
    } else {
      if (_dateLeft.getMonth() === 1 && _dateLeft.getDate() > 27) {
        _dateLeft.setDate(30);
      }
      _dateLeft.setMonth(_dateLeft.getMonth() - sign * difference);
      var isLastMonthNotFull = _compareAsc(_dateLeft, _dateRight) === -sign;
      if (_isLastDayOfMonth(_toDate(dateLeft)) && difference === 1 && _compareAsc(dateLeft, _dateRight) === 1) {
        isLastMonthNotFull = false;
      }
      result = sign * (difference - Number(isLastMonthNotFull));
    }
    return result === 0 ? 0 : result;
  }
  // lib/differenceInQuarters.mjs
  function _differenceInQuarters(dateLeft, dateRight, options) {
    var diff = _differenceInMonths(dateLeft, dateRight) / 3;
    return getRoundingMethod(options === null || options === void 0 ? void 0 : options.roundingMethod)(diff);
  }
  // lib/differenceInSeconds.mjs
  function _differenceInSeconds(dateLeft, dateRight, options) {
    var diff = _differenceInMilliseconds(dateLeft, dateRight) / 1000;
    return getRoundingMethod(options === null || options === void 0 ? void 0 : options.roundingMethod)(diff);
  }
  // lib/differenceInWeeks.mjs
  function _differenceInWeeks(dateLeft, dateRight, options) {
    var diff = _differenceInDays(dateLeft, dateRight) / 7;
    return getRoundingMethod(options === null || options === void 0 ? void 0 : options.roundingMethod)(diff);
  }
  // lib/differenceInYears.mjs
  function _differenceInYears(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    var sign = _compareAsc(_dateLeft, _dateRight);
    var difference = Math.abs(_differenceInCalendarYears(_dateLeft, _dateRight));
    _dateLeft.setFullYear(1584);
    _dateRight.setFullYear(1584);
    var isLastYearNotFull = _compareAsc(_dateLeft, _dateRight) === -sign;
    var result = sign * (difference - +isLastYearNotFull);
    return result === 0 ? 0 : result;
  }
  // lib/eachDayOfInterval.mjs
  function _eachDayOfInterval(interval, options) {var _options$step;
    var startDate = _toDate(interval.start);
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var endTime = reversed ? +startDate : +endDate;
    var currentDate = reversed ? endDate : startDate;
    currentDate.setHours(0, 0, 0, 0);
    var step = (_options$step = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step !== void 0 ? _options$step : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      dates.push(_toDate(currentDate));
      currentDate.setDate(currentDate.getDate() + step);
      currentDate.setHours(0, 0, 0, 0);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/eachHourOfInterval.mjs
  function _eachHourOfInterval(interval, options) {var _options$step2;
    var startDate = _toDate(interval.start);
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var endTime = reversed ? +startDate : +endDate;
    var currentDate = reversed ? endDate : startDate;
    currentDate.setMinutes(0, 0, 0);
    var step = (_options$step2 = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step2 !== void 0 ? _options$step2 : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      dates.push(_toDate(currentDate));
      currentDate = _addHours(currentDate, step);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/startOfMinute.mjs
  function _startOfMinute(date) {
    var _date = _toDate(date);
    _date.setSeconds(0, 0);
    return _date;
  }

  // lib/eachMinuteOfInterval.mjs
  function _eachMinuteOfInterval(interval, options) {var _options$step3;
    var startDate = _startOfMinute(_toDate(interval.start));
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var endTime = reversed ? +startDate : +endDate;
    var currentDate = reversed ? endDate : startDate;
    var step = (_options$step3 = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step3 !== void 0 ? _options$step3 : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      dates.push(_toDate(currentDate));
      currentDate = _addMinutes(currentDate, step);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/eachMonthOfInterval.mjs
  function _eachMonthOfInterval(interval, options) {var _options$step4;
    var startDate = _toDate(interval.start);
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var endTime = reversed ? +startDate : +endDate;
    var currentDate = reversed ? endDate : startDate;
    currentDate.setHours(0, 0, 0, 0);
    currentDate.setDate(1);
    var step = (_options$step4 = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step4 !== void 0 ? _options$step4 : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      dates.push(_toDate(currentDate));
      currentDate.setMonth(currentDate.getMonth() + step);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/startOfQuarter.mjs
  function _startOfQuarter(date) {
    var _date = _toDate(date);
    var currentMonth = _date.getMonth();
    var month = currentMonth - currentMonth % 3;
    _date.setMonth(month, 1);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/eachQuarterOfInterval.mjs
  function _eachQuarterOfInterval(interval, options) {var _options$step5;
    var startDate = _toDate(interval.start);
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var endTime = reversed ? +_startOfQuarter(startDate) : +_startOfQuarter(endDate);
    var currentDate = reversed ? _startOfQuarter(endDate) : _startOfQuarter(startDate);
    var step = (_options$step5 = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step5 !== void 0 ? _options$step5 : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      dates.push(_toDate(currentDate));
      currentDate = _addQuarters(currentDate, step);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/eachWeekOfInterval.mjs
  function _eachWeekOfInterval(interval, options) {var _options$step6;
    var startDate = _toDate(interval.start);
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var startDateWeek = reversed ? _startOfWeek(endDate, options) : _startOfWeek(startDate, options);
    var endDateWeek = reversed ? _startOfWeek(startDate, options) : _startOfWeek(endDate, options);
    startDateWeek.setHours(15);
    endDateWeek.setHours(15);
    var endTime = +endDateWeek.getTime();
    var currentDate = startDateWeek;
    var step = (_options$step6 = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step6 !== void 0 ? _options$step6 : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      currentDate.setHours(0);
      dates.push(_toDate(currentDate));
      currentDate = _addWeeks(currentDate, step);
      currentDate.setHours(15);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/eachWeekendOfInterval.mjs
  function _eachWeekendOfInterval(interval) {
    var dateInterval = _eachDayOfInterval(interval);
    var weekends = [];
    var index = 0;
    while (index < dateInterval.length) {
      var date = dateInterval[index++];
      if (_isWeekend(date))
      weekends.push(date);
    }
    return weekends;
  }
  // lib/startOfMonth.mjs
  function _startOfMonth(date) {
    var _date = _toDate(date);
    _date.setDate(1);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/eachWeekendOfMonth.mjs
  function _eachWeekendOfMonth(date) {
    var start = _startOfMonth(date);
    var end = _endOfMonth(date);
    return _eachWeekendOfInterval({ start: start, end: end });
  }
  // lib/endOfYear.mjs
  function _endOfYear(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    _date.setFullYear(year + 1, 0, 0);
    _date.setHours(23, 59, 59, 999);
    return _date;
  }

  // lib/startOfYear.mjs
  function _startOfYear(date) {
    var cleanDate = _toDate(date);
    var _date = _constructFrom(date, 0);
    _date.setFullYear(cleanDate.getFullYear(), 0, 1);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/eachWeekendOfYear.mjs
  function _eachWeekendOfYear(date) {
    var start = _startOfYear(date);
    var end = _endOfYear(date);
    return _eachWeekendOfInterval({ start: start, end: end });
  }
  // lib/eachYearOfInterval.mjs
  function _eachYearOfInterval(interval, options) {var _options$step7;
    var startDate = _toDate(interval.start);
    var endDate = _toDate(interval.end);
    var reversed = +startDate > +endDate;
    var endTime = reversed ? +startDate : +endDate;
    var currentDate = reversed ? endDate : startDate;
    currentDate.setHours(0, 0, 0, 0);
    currentDate.setMonth(0, 1);
    var step = (_options$step7 = options === null || options === void 0 ? void 0 : options.step) !== null && _options$step7 !== void 0 ? _options$step7 : 1;
    if (!step)
    return [];
    if (step < 0) {
      step = -step;
      reversed = !reversed;
    }
    var dates = [];
    while (+currentDate <= endTime) {
      dates.push(_toDate(currentDate));
      currentDate.setFullYear(currentDate.getFullYear() + step);
    }
    return reversed ? dates.reverse() : dates;
  }
  // lib/endOfDecade.mjs
  function _endOfDecade(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var decade = 9 + Math.floor(year / 10) * 10;
    _date.setFullYear(decade, 11, 31);
    _date.setHours(23, 59, 59, 999);
    return _date;
  }
  // lib/endOfHour.mjs
  function _endOfHour(date) {
    var _date = _toDate(date);
    _date.setMinutes(59, 59, 999);
    return _date;
  }
  // lib/endOfWeek.mjs
  function _endOfWeek(date, options) {var _ref4, _ref5, _ref6, _options$weekStartsOn2, _options$locale2, _defaultOptions4$loca;
    var defaultOptions4 = getDefaultOptions();
    var weekStartsOn = (_ref4 = (_ref5 = (_ref6 = (_options$weekStartsOn2 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn2 !== void 0 ? _options$weekStartsOn2 : options === null || options === void 0 || (_options$locale2 = options.locale) === null || _options$locale2 === void 0 || (_options$locale2 = _options$locale2.options) === null || _options$locale2 === void 0 ? void 0 : _options$locale2.weekStartsOn) !== null && _ref6 !== void 0 ? _ref6 : defaultOptions4.weekStartsOn) !== null && _ref5 !== void 0 ? _ref5 : (_defaultOptions4$loca = defaultOptions4.locale) === null || _defaultOptions4$loca === void 0 || (_defaultOptions4$loca = _defaultOptions4$loca.options) === null || _defaultOptions4$loca === void 0 ? void 0 : _defaultOptions4$loca.weekStartsOn) !== null && _ref4 !== void 0 ? _ref4 : 0;
    var _date = _toDate(date);
    var day = _date.getDay();
    var diff = (day < weekStartsOn ? -7 : 0) + 6 - (day - weekStartsOn);
    _date.setDate(_date.getDate() + diff);
    _date.setHours(23, 59, 59, 999);
    return _date;
  }

  // lib/endOfISOWeek.mjs
  function _endOfISOWeek(date) {
    return _endOfWeek(date, { weekStartsOn: 1 });
  }
  // lib/endOfISOWeekYear.mjs
  function _endOfISOWeekYear(date) {
    var year = _getISOWeekYear(date);
    var fourthOfJanuaryOfNextYear = _constructFrom(date, 0);
    fourthOfJanuaryOfNextYear.setFullYear(year + 1, 0, 4);
    fourthOfJanuaryOfNextYear.setHours(0, 0, 0, 0);
    var _date = _startOfISOWeek(fourthOfJanuaryOfNextYear);
    _date.setMilliseconds(_date.getMilliseconds() - 1);
    return _date;
  }
  // lib/endOfMinute.mjs
  function _endOfMinute(date) {
    var _date = _toDate(date);
    _date.setSeconds(59, 999);
    return _date;
  }
  // lib/endOfQuarter.mjs
  function _endOfQuarter(date) {
    var _date = _toDate(date);
    var currentMonth = _date.getMonth();
    var month = currentMonth - currentMonth % 3 + 3;
    _date.setMonth(month, 0);
    _date.setHours(23, 59, 59, 999);
    return _date;
  }
  // lib/endOfSecond.mjs
  function _endOfSecond(date) {
    var _date = _toDate(date);
    _date.setMilliseconds(999);
    return _date;
  }
  // lib/endOfToday.mjs
  function _endOfToday() {
    return _endOfDay(Date.now());
  }
  // lib/endOfTomorrow.mjs
  function _endOfTomorrow() {
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth();
    var day = now.getDate();
    var date = new Date(0);
    date.setFullYear(year, month, day + 1);
    date.setHours(23, 59, 59, 999);
    return date;
  }
  // lib/endOfYesterday.mjs
  function _endOfYesterday() {
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth();
    var day = now.getDate();
    var date = new Date(0);
    date.setFullYear(year, month, day - 1);
    date.setHours(23, 59, 59, 999);
    return date;
  }
  // lib/locale/en-US/_lib/formatDistance.mjs
  var formatDistanceLocale = {
    lessThanXSeconds: {
      one: "less than a second",
      other: "less than {{count}} seconds"
    },
    xSeconds: {
      one: "1 second",
      other: "{{count}} seconds"
    },
    halfAMinute: "half a minute",
    lessThanXMinutes: {
      one: "less than a minute",
      other: "less than {{count}} minutes"
    },
    xMinutes: {
      one: "1 minute",
      other: "{{count}} minutes"
    },
    aboutXHours: {
      one: "about 1 hour",
      other: "about {{count}} hours"
    },
    xHours: {
      one: "1 hour",
      other: "{{count}} hours"
    },
    xDays: {
      one: "1 day",
      other: "{{count}} days"
    },
    aboutXWeeks: {
      one: "about 1 week",
      other: "about {{count}} weeks"
    },
    xWeeks: {
      one: "1 week",
      other: "{{count}} weeks"
    },
    aboutXMonths: {
      one: "about 1 month",
      other: "about {{count}} months"
    },
    xMonths: {
      one: "1 month",
      other: "{{count}} months"
    },
    aboutXYears: {
      one: "about 1 year",
      other: "about {{count}} years"
    },
    xYears: {
      one: "1 year",
      other: "{{count}} years"
    },
    overXYears: {
      one: "over 1 year",
      other: "over {{count}} years"
    },
    almostXYears: {
      one: "almost 1 year",
      other: "almost {{count}} years"
    }
  };
  var formatDistance = function formatDistance(token, count, options) {
    var result;
    var tokenValue = formatDistanceLocale[token];
    if (typeof tokenValue === "string") {
      result = tokenValue;
    } else if (count === 1) {
      result = tokenValue.one;
    } else {
      result = tokenValue.other.replace("{{count}}", count.toString());
    }
    if (options !== null && options !== void 0 && options.addSuffix) {
      if (options.comparison && options.comparison > 0) {
        return "in " + result;
      } else {
        return result + " ago";
      }
    }
    return result;
  };

  // lib/locale/_lib/buildFormatLongFn.mjs
  function buildFormatLongFn(args) {
    return function () {var options = arguments.length > 0 && arguments[0] !== undefined ? arguments[0] : {};
      var width = options.width ? String(options.width) : args.defaultWidth;
      var format = args.formats[width] || args.formats[args.defaultWidth];
      return format;
    };
  }

  // lib/locale/en-US/_lib/formatLong.mjs
  var dateFormats = {
    full: "EEEE, MMMM do, y",
    long: "MMMM do, y",
    medium: "MMM d, y",
    short: "MM/dd/yyyy"
  };
  var timeFormats = {
    full: "h:mm:ss a zzzz",
    long: "h:mm:ss a z",
    medium: "h:mm:ss a",
    short: "h:mm a"
  };
  var dateTimeFormats = {
    full: "{{date}} 'at' {{time}}",
    long: "{{date}} 'at' {{time}}",
    medium: "{{date}}, {{time}}",
    short: "{{date}}, {{time}}"
  };
  var formatLong = {
    date: buildFormatLongFn({
      formats: dateFormats,
      defaultWidth: "full"
    }),
    time: buildFormatLongFn({
      formats: timeFormats,
      defaultWidth: "full"
    }),
    dateTime: buildFormatLongFn({
      formats: dateTimeFormats,
      defaultWidth: "full"
    })
  };

  // lib/locale/en-US/_lib/formatRelative.mjs
  var formatRelativeLocale = {
    lastWeek: "'last' eeee 'at' p",
    yesterday: "'yesterday at' p",
    today: "'today at' p",
    tomorrow: "'tomorrow at' p",
    nextWeek: "eeee 'at' p",
    other: "P"
  };
  var formatRelative = function formatRelative(token, _date, _baseDate, _options) {return formatRelativeLocale[token];};

  // lib/locale/_lib/buildLocalizeFn.mjs
  function buildLocalizeFn(args) {
    return function (value, options) {
      var context = options !== null && options !== void 0 && options.context ? String(options.context) : "standalone";
      var valuesArray;
      if (context === "formatting" && args.formattingValues) {
        var defaultWidth = args.defaultFormattingWidth || args.defaultWidth;
        var width = options !== null && options !== void 0 && options.width ? String(options.width) : defaultWidth;
        valuesArray = args.formattingValues[width] || args.formattingValues[defaultWidth];
      } else {
        var _defaultWidth = args.defaultWidth;
        var _width = options !== null && options !== void 0 && options.width ? String(options.width) : args.defaultWidth;
        valuesArray = args.values[_width] || args.values[_defaultWidth];
      }
      var index = args.argumentCallback ? args.argumentCallback(value) : value;
      return valuesArray[index];
    };
  }

  // lib/locale/en-US/_lib/localize.mjs
  var eraValues = {
    narrow: ["B", "A"],
    abbreviated: ["BC", "AD"],
    wide: ["Before Christ", "Anno Domini"]
  };
  var quarterValues = {
    narrow: ["1", "2", "3", "4"],
    abbreviated: ["Q1", "Q2", "Q3", "Q4"],
    wide: ["1st quarter", "2nd quarter", "3rd quarter", "4th quarter"]
  };
  var monthValues = {
    narrow: ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
    abbreviated: [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec"],

    wide: [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December"]

  };
  var dayValues = {
    narrow: ["S", "M", "T", "W", "T", "F", "S"],
    short: ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"],
    abbreviated: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    wide: [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday"]

  };
  var dayPeriodValues = {
    narrow: {
      am: "a",
      pm: "p",
      midnight: "mi",
      noon: "n",
      morning: "morning",
      afternoon: "afternoon",
      evening: "evening",
      night: "night"
    },
    abbreviated: {
      am: "AM",
      pm: "PM",
      midnight: "midnight",
      noon: "noon",
      morning: "morning",
      afternoon: "afternoon",
      evening: "evening",
      night: "night"
    },
    wide: {
      am: "a.m.",
      pm: "p.m.",
      midnight: "midnight",
      noon: "noon",
      morning: "morning",
      afternoon: "afternoon",
      evening: "evening",
      night: "night"
    }
  };
  var formattingDayPeriodValues = {
    narrow: {
      am: "a",
      pm: "p",
      midnight: "mi",
      noon: "n",
      morning: "in the morning",
      afternoon: "in the afternoon",
      evening: "in the evening",
      night: "at night"
    },
    abbreviated: {
      am: "AM",
      pm: "PM",
      midnight: "midnight",
      noon: "noon",
      morning: "in the morning",
      afternoon: "in the afternoon",
      evening: "in the evening",
      night: "at night"
    },
    wide: {
      am: "a.m.",
      pm: "p.m.",
      midnight: "midnight",
      noon: "noon",
      morning: "in the morning",
      afternoon: "in the afternoon",
      evening: "in the evening",
      night: "at night"
    }
  };
  var ordinalNumber = function ordinalNumber(dirtyNumber, _options) {
    var number = Number(dirtyNumber);
    var rem100 = number % 100;
    if (rem100 > 20 || rem100 < 10) {
      switch (rem100 % 10) {
        case 1:
          return number + "st";
        case 2:
          return number + "nd";
        case 3:
          return number + "rd";
      }
    }
    return number + "th";
  };
  var localize = {
    ordinalNumber: ordinalNumber,
    era: buildLocalizeFn({
      values: eraValues,
      defaultWidth: "wide"
    }),
    quarter: buildLocalizeFn({
      values: quarterValues,
      defaultWidth: "wide",
      argumentCallback: function argumentCallback(quarter) {return quarter - 1;}
    }),
    month: buildLocalizeFn({
      values: monthValues,
      defaultWidth: "wide"
    }),
    day: buildLocalizeFn({
      values: dayValues,
      defaultWidth: "wide"
    }),
    dayPeriod: buildLocalizeFn({
      values: dayPeriodValues,
      defaultWidth: "wide",
      formattingValues: formattingDayPeriodValues,
      defaultFormattingWidth: "wide"
    })
  };

  // lib/locale/_lib/buildMatchFn.mjs
  function buildMatchFn(args) {
    return function (string) {var options = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : {};
      var width = options.width;
      var matchPattern = width && args.matchPatterns[width] || args.matchPatterns[args.defaultMatchWidth];
      var matchResult = string.match(matchPattern);
      if (!matchResult) {
        return null;
      }
      var matchedString = matchResult[0];
      var parsePatterns = width && args.parsePatterns[width] || args.parsePatterns[args.defaultParseWidth];
      var key = Array.isArray(parsePatterns) ? findIndex(parsePatterns, function (pattern) {return pattern.test(matchedString);}) : findKey(parsePatterns, function (pattern) {return pattern.test(matchedString);});
      var value;
      value = args.valueCallback ? args.valueCallback(key) : key;
      value = options.valueCallback ? options.valueCallback(value) : value;
      var rest = string.slice(matchedString.length);
      return { value: value, rest: rest };
    };
  }
  var findKey = function findKey(object, predicate) {
    for (var key in object) {
      if (Object.prototype.hasOwnProperty.call(object, key) && predicate(object[key])) {
        return key;
      }
    }
    return;
  };
  var findIndex = function findIndex(array, predicate) {
    for (var key = 0; key < array.length; key++) {
      if (predicate(array[key])) {
        return key;
      }
    }
    return;
  };

  // lib/locale/_lib/buildMatchPatternFn.mjs
  function buildMatchPatternFn(args) {
    return function (string) {var options = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : {};
      var matchResult = string.match(args.matchPattern);
      if (!matchResult)
      return null;
      var matchedString = matchResult[0];
      var parseResult = string.match(args.parsePattern);
      if (!parseResult)
      return null;
      var value = args.valueCallback ? args.valueCallback(parseResult[0]) : parseResult[0];
      value = options.valueCallback ? options.valueCallback(value) : value;
      var rest = string.slice(matchedString.length);
      return { value: value, rest: rest };
    };
  }

  // lib/locale/en-US/_lib/match.mjs
  var matchOrdinalNumberPattern = /^(\d+)(th|st|nd|rd)?/i;
  var parseOrdinalNumberPattern = /\d+/i;
  var matchEraPatterns = {
    narrow: /^(b|a)/i,
    abbreviated: /^(b\.?\s?c\.?|b\.?\s?c\.?\s?e\.?|a\.?\s?d\.?|c\.?\s?e\.?)/i,
    wide: /^(before christ|before common era|anno domini|common era)/i
  };
  var parseEraPatterns = {
    any: [/^b/i, /^(a|c)/i]
  };
  var matchQuarterPatterns = {
    narrow: /^[1234]/i,
    abbreviated: /^q[1234]/i,
    wide: /^[1234](th|st|nd|rd)? quarter/i
  };
  var parseQuarterPatterns = {
    any: [/1/i, /2/i, /3/i, /4/i]
  };
  var matchMonthPatterns = {
    narrow: /^[jfmasond]/i,
    abbreviated: /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i,
    wide: /^(january|february|march|april|may|june|july|august|september|october|november|december)/i
  };
  var parseMonthPatterns = {
    narrow: [
    /^j/i,
    /^f/i,
    /^m/i,
    /^a/i,
    /^m/i,
    /^j/i,
    /^j/i,
    /^a/i,
    /^s/i,
    /^o/i,
    /^n/i,
    /^d/i],

    any: [
    /^ja/i,
    /^f/i,
    /^mar/i,
    /^ap/i,
    /^may/i,
    /^jun/i,
    /^jul/i,
    /^au/i,
    /^s/i,
    /^o/i,
    /^n/i,
    /^d/i]

  };
  var matchDayPatterns = {
    narrow: /^[smtwf]/i,
    short: /^(su|mo|tu|we|th|fr|sa)/i,
    abbreviated: /^(sun|mon|tue|wed|thu|fri|sat)/i,
    wide: /^(sunday|monday|tuesday|wednesday|thursday|friday|saturday)/i
  };
  var parseDayPatterns = {
    narrow: [/^s/i, /^m/i, /^t/i, /^w/i, /^t/i, /^f/i, /^s/i],
    any: [/^su/i, /^m/i, /^tu/i, /^w/i, /^th/i, /^f/i, /^sa/i]
  };
  var matchDayPeriodPatterns = {
    narrow: /^(a|p|mi|n|(in the|at) (morning|afternoon|evening|night))/i,
    any: /^([ap]\.?\s?m\.?|midnight|noon|(in the|at) (morning|afternoon|evening|night))/i
  };
  var parseDayPeriodPatterns = {
    any: {
      am: /^a/i,
      pm: /^p/i,
      midnight: /^mi/i,
      noon: /^no/i,
      morning: /morning/i,
      afternoon: /afternoon/i,
      evening: /evening/i,
      night: /night/i
    }
  };
  var match = {
    ordinalNumber: buildMatchPatternFn({
      matchPattern: matchOrdinalNumberPattern,
      parsePattern: parseOrdinalNumberPattern,
      valueCallback: function valueCallback(value) {return parseInt(value, 10);}
    }),
    era: buildMatchFn({
      matchPatterns: matchEraPatterns,
      defaultMatchWidth: "wide",
      parsePatterns: parseEraPatterns,
      defaultParseWidth: "any"
    }),
    quarter: buildMatchFn({
      matchPatterns: matchQuarterPatterns,
      defaultMatchWidth: "wide",
      parsePatterns: parseQuarterPatterns,
      defaultParseWidth: "any",
      valueCallback: function valueCallback(index) {return index + 1;}
    }),
    month: buildMatchFn({
      matchPatterns: matchMonthPatterns,
      defaultMatchWidth: "wide",
      parsePatterns: parseMonthPatterns,
      defaultParseWidth: "any"
    }),
    day: buildMatchFn({
      matchPatterns: matchDayPatterns,
      defaultMatchWidth: "wide",
      parsePatterns: parseDayPatterns,
      defaultParseWidth: "any"
    }),
    dayPeriod: buildMatchFn({
      matchPatterns: matchDayPeriodPatterns,
      defaultMatchWidth: "any",
      parsePatterns: parseDayPeriodPatterns,
      defaultParseWidth: "any"
    })
  };

  // lib/locale/en-US.mjs
  var enUS = {
    code: "en-US",
    formatDistance: formatDistance,
    formatLong: formatLong,
    formatRelative: formatRelative,
    localize: localize,
    match: match,
    options: {
      weekStartsOn: 0,
      firstWeekContainsDate: 1
    }
  };
  // lib/getDayOfYear.mjs
  function _getDayOfYear(date) {
    var _date = _toDate(date);
    var diff = _differenceInCalendarDays(_date, _startOfYear(_date));
    var dayOfYear = diff + 1;
    return dayOfYear;
  }

  // lib/getISOWeek.mjs
  function _getISOWeek(date) {
    var _date = _toDate(date);
    var diff = +_startOfISOWeek(_date) - +_startOfISOWeekYear(_date);
    return Math.round(diff / millisecondsInWeek) + 1;
  }

  // lib/getWeekYear.mjs
  function _getWeekYear(date, options) {var _ref7, _ref8, _ref9, _options$firstWeekCon, _options$locale3, _defaultOptions5$loca;
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var defaultOptions5 = getDefaultOptions();
    var firstWeekContainsDate = (_ref7 = (_ref8 = (_ref9 = (_options$firstWeekCon = options === null || options === void 0 ? void 0 : options.firstWeekContainsDate) !== null && _options$firstWeekCon !== void 0 ? _options$firstWeekCon : options === null || options === void 0 || (_options$locale3 = options.locale) === null || _options$locale3 === void 0 || (_options$locale3 = _options$locale3.options) === null || _options$locale3 === void 0 ? void 0 : _options$locale3.firstWeekContainsDate) !== null && _ref9 !== void 0 ? _ref9 : defaultOptions5.firstWeekContainsDate) !== null && _ref8 !== void 0 ? _ref8 : (_defaultOptions5$loca = defaultOptions5.locale) === null || _defaultOptions5$loca === void 0 || (_defaultOptions5$loca = _defaultOptions5$loca.options) === null || _defaultOptions5$loca === void 0 ? void 0 : _defaultOptions5$loca.firstWeekContainsDate) !== null && _ref7 !== void 0 ? _ref7 : 1;
    var firstWeekOfNextYear = _constructFrom(date, 0);
    firstWeekOfNextYear.setFullYear(year + 1, 0, firstWeekContainsDate);
    firstWeekOfNextYear.setHours(0, 0, 0, 0);
    var startOfNextYear = _startOfWeek(firstWeekOfNextYear, options);
    var firstWeekOfThisYear = _constructFrom(date, 0);
    firstWeekOfThisYear.setFullYear(year, 0, firstWeekContainsDate);
    firstWeekOfThisYear.setHours(0, 0, 0, 0);
    var startOfThisYear = _startOfWeek(firstWeekOfThisYear, options);
    if (_date.getTime() >= startOfNextYear.getTime()) {
      return year + 1;
    } else if (_date.getTime() >= startOfThisYear.getTime()) {
      return year;
    } else {
      return year - 1;
    }
  }

  // lib/startOfWeekYear.mjs
  function _startOfWeekYear(date, options) {var _ref10, _ref11, _ref12, _options$firstWeekCon2, _options$locale4, _defaultOptions6$loca;
    var defaultOptions6 = getDefaultOptions();
    var firstWeekContainsDate = (_ref10 = (_ref11 = (_ref12 = (_options$firstWeekCon2 = options === null || options === void 0 ? void 0 : options.firstWeekContainsDate) !== null && _options$firstWeekCon2 !== void 0 ? _options$firstWeekCon2 : options === null || options === void 0 || (_options$locale4 = options.locale) === null || _options$locale4 === void 0 || (_options$locale4 = _options$locale4.options) === null || _options$locale4 === void 0 ? void 0 : _options$locale4.firstWeekContainsDate) !== null && _ref12 !== void 0 ? _ref12 : defaultOptions6.firstWeekContainsDate) !== null && _ref11 !== void 0 ? _ref11 : (_defaultOptions6$loca = defaultOptions6.locale) === null || _defaultOptions6$loca === void 0 || (_defaultOptions6$loca = _defaultOptions6$loca.options) === null || _defaultOptions6$loca === void 0 ? void 0 : _defaultOptions6$loca.firstWeekContainsDate) !== null && _ref10 !== void 0 ? _ref10 : 1;
    var year = _getWeekYear(date, options);
    var firstWeek = _constructFrom(date, 0);
    firstWeek.setFullYear(year, 0, firstWeekContainsDate);
    firstWeek.setHours(0, 0, 0, 0);
    var _date = _startOfWeek(firstWeek, options);
    return _date;
  }

  // lib/getWeek.mjs
  function _getWeek(date, options) {
    var _date = _toDate(date);
    var diff = +_startOfWeek(_date, options) - +_startOfWeekYear(_date, options);
    return Math.round(diff / millisecondsInWeek) + 1;
  }

  // lib/_lib/addLeadingZeros.mjs
  function addLeadingZeros(number, targetLength) {
    var sign = number < 0 ? "-" : "";
    var output = Math.abs(number).toString().padStart(targetLength, "0");
    return sign + output;
  }

  // lib/_lib/format/lightFormatters.mjs
  var _lightFormatters = {
    y: function y(date, token) {
      var signedYear = date.getFullYear();
      var year = signedYear > 0 ? signedYear : 1 - signedYear;
      return addLeadingZeros(token === "yy" ? year % 100 : year, token.length);
    },
    M: function M(date, token) {
      var month = date.getMonth();
      return token === "M" ? String(month + 1) : addLeadingZeros(month + 1, 2);
    },
    d: function d(date, token) {
      return addLeadingZeros(date.getDate(), token.length);
    },
    a: function a(date, token) {
      var dayPeriodEnumValue = date.getHours() / 12 >= 1 ? "pm" : "am";
      switch (token) {
        case "a":
        case "aa":
          return dayPeriodEnumValue.toUpperCase();
        case "aaa":
          return dayPeriodEnumValue;
        case "aaaaa":
          return dayPeriodEnumValue[0];
        case "aaaa":
        default:
          return dayPeriodEnumValue === "am" ? "a.m." : "p.m.";
      }
    },
    h: function h(date, token) {
      return addLeadingZeros(date.getHours() % 12 || 12, token.length);
    },
    H: function H(date, token) {
      return addLeadingZeros(date.getHours(), token.length);
    },
    m: function m(date, token) {
      return addLeadingZeros(date.getMinutes(), token.length);
    },
    s: function s(date, token) {
      return addLeadingZeros(date.getSeconds(), token.length);
    },
    S: function S(date, token) {
      var numberOfDigits = token.length;
      var milliseconds = date.getMilliseconds();
      var fractionalSeconds = Math.trunc(milliseconds * Math.pow(10, numberOfDigits - 3));
      return addLeadingZeros(fractionalSeconds, token.length);
    }
  };

  // lib/_lib/format/formatters.mjs
  var formatTimezoneShort = function formatTimezoneShort(offset) {var delimiter = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : "";
    var sign = offset > 0 ? "-" : "+";
    var absOffset = Math.abs(offset);
    var hours = Math.trunc(absOffset / 60);
    var minutes = absOffset % 60;
    if (minutes === 0) {
      return sign + String(hours);
    }
    return sign + String(hours) + delimiter + addLeadingZeros(minutes, 2);
  };
  var formatTimezoneWithOptionalMinutes = function formatTimezoneWithOptionalMinutes(offset, delimiter) {
    if (offset % 60 === 0) {
      var sign = offset > 0 ? "-" : "+";
      return sign + addLeadingZeros(Math.abs(offset) / 60, 2);
    }
    return formatTimezone(offset, delimiter);
  };
  var formatTimezone = function formatTimezone(offset) {var delimiter = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : "";
    var sign = offset > 0 ? "-" : "+";
    var absOffset = Math.abs(offset);
    var hours = addLeadingZeros(Math.trunc(absOffset / 60), 2);
    var minutes = addLeadingZeros(absOffset % 60, 2);
    return sign + hours + delimiter + minutes;
  };
  var dayPeriodEnum = {
    am: "am",
    pm: "pm",
    midnight: "midnight",
    noon: "noon",
    morning: "morning",
    afternoon: "afternoon",
    evening: "evening",
    night: "night"
  };
  var _formatters = {
    G: function G(date, token, localize3) {
      var era = date.getFullYear() > 0 ? 1 : 0;
      switch (token) {
        case "G":
        case "GG":
        case "GGG":
          return localize3.era(era, { width: "abbreviated" });
        case "GGGGG":
          return localize3.era(era, { width: "narrow" });
        case "GGGG":
        default:
          return localize3.era(era, { width: "wide" });
      }
    },
    y: function y(date, token, localize3) {
      if (token === "yo") {
        var signedYear = date.getFullYear();
        var year = signedYear > 0 ? signedYear : 1 - signedYear;
        return localize3.ordinalNumber(year, { unit: "year" });
      }
      return _lightFormatters.y(date, token);
    },
    Y: function Y(date, token, localize3, options) {
      var signedWeekYear = _getWeekYear(date, options);
      var weekYear = signedWeekYear > 0 ? signedWeekYear : 1 - signedWeekYear;
      if (token === "YY") {
        var twoDigitYear = weekYear % 100;
        return addLeadingZeros(twoDigitYear, 2);
      }
      if (token === "Yo") {
        return localize3.ordinalNumber(weekYear, { unit: "year" });
      }
      return addLeadingZeros(weekYear, token.length);
    },
    R: function R(date, token) {
      var isoWeekYear = _getISOWeekYear(date);
      return addLeadingZeros(isoWeekYear, token.length);
    },
    u: function u(date, token) {
      var year = date.getFullYear();
      return addLeadingZeros(year, token.length);
    },
    Q: function Q(date, token, localize3) {
      var quarter = Math.ceil((date.getMonth() + 1) / 3);
      switch (token) {
        case "Q":
          return String(quarter);
        case "QQ":
          return addLeadingZeros(quarter, 2);
        case "Qo":
          return localize3.ordinalNumber(quarter, { unit: "quarter" });
        case "QQQ":
          return localize3.quarter(quarter, {
            width: "abbreviated",
            context: "formatting"
          });
        case "QQQQQ":
          return localize3.quarter(quarter, {
            width: "narrow",
            context: "formatting"
          });
        case "QQQQ":
        default:
          return localize3.quarter(quarter, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    q: function q(date, token, localize3) {
      var quarter = Math.ceil((date.getMonth() + 1) / 3);
      switch (token) {
        case "q":
          return String(quarter);
        case "qq":
          return addLeadingZeros(quarter, 2);
        case "qo":
          return localize3.ordinalNumber(quarter, { unit: "quarter" });
        case "qqq":
          return localize3.quarter(quarter, {
            width: "abbreviated",
            context: "standalone"
          });
        case "qqqqq":
          return localize3.quarter(quarter, {
            width: "narrow",
            context: "standalone"
          });
        case "qqqq":
        default:
          return localize3.quarter(quarter, {
            width: "wide",
            context: "standalone"
          });
      }
    },
    M: function M(date, token, localize3) {
      var month = date.getMonth();
      switch (token) {
        case "M":
        case "MM":
          return _lightFormatters.M(date, token);
        case "Mo":
          return localize3.ordinalNumber(month + 1, { unit: "month" });
        case "MMM":
          return localize3.month(month, {
            width: "abbreviated",
            context: "formatting"
          });
        case "MMMMM":
          return localize3.month(month, {
            width: "narrow",
            context: "formatting"
          });
        case "MMMM":
        default:
          return localize3.month(month, { width: "wide", context: "formatting" });
      }
    },
    L: function L(date, token, localize3) {
      var month = date.getMonth();
      switch (token) {
        case "L":
          return String(month + 1);
        case "LL":
          return addLeadingZeros(month + 1, 2);
        case "Lo":
          return localize3.ordinalNumber(month + 1, { unit: "month" });
        case "LLL":
          return localize3.month(month, {
            width: "abbreviated",
            context: "standalone"
          });
        case "LLLLL":
          return localize3.month(month, {
            width: "narrow",
            context: "standalone"
          });
        case "LLLL":
        default:
          return localize3.month(month, { width: "wide", context: "standalone" });
      }
    },
    w: function w(date, token, localize3, options) {
      var week = _getWeek(date, options);
      if (token === "wo") {
        return localize3.ordinalNumber(week, { unit: "week" });
      }
      return addLeadingZeros(week, token.length);
    },
    I: function I(date, token, localize3) {
      var isoWeek = _getISOWeek(date);
      if (token === "Io") {
        return localize3.ordinalNumber(isoWeek, { unit: "week" });
      }
      return addLeadingZeros(isoWeek, token.length);
    },
    d: function d(date, token, localize3) {
      if (token === "do") {
        return localize3.ordinalNumber(date.getDate(), { unit: "date" });
      }
      return _lightFormatters.d(date, token);
    },
    D: function D(date, token, localize3) {
      var dayOfYear = _getDayOfYear(date);
      if (token === "Do") {
        return localize3.ordinalNumber(dayOfYear, { unit: "dayOfYear" });
      }
      return addLeadingZeros(dayOfYear, token.length);
    },
    E: function E(date, token, localize3) {
      var dayOfWeek = date.getDay();
      switch (token) {
        case "E":
        case "EE":
        case "EEE":
          return localize3.day(dayOfWeek, {
            width: "abbreviated",
            context: "formatting"
          });
        case "EEEEE":
          return localize3.day(dayOfWeek, {
            width: "narrow",
            context: "formatting"
          });
        case "EEEEEE":
          return localize3.day(dayOfWeek, {
            width: "short",
            context: "formatting"
          });
        case "EEEE":
        default:
          return localize3.day(dayOfWeek, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    e: function e(date, token, localize3, options) {
      var dayOfWeek = date.getDay();
      var localDayOfWeek = (dayOfWeek - options.weekStartsOn + 8) % 7 || 7;
      switch (token) {
        case "e":
          return String(localDayOfWeek);
        case "ee":
          return addLeadingZeros(localDayOfWeek, 2);
        case "eo":
          return localize3.ordinalNumber(localDayOfWeek, { unit: "day" });
        case "eee":
          return localize3.day(dayOfWeek, {
            width: "abbreviated",
            context: "formatting"
          });
        case "eeeee":
          return localize3.day(dayOfWeek, {
            width: "narrow",
            context: "formatting"
          });
        case "eeeeee":
          return localize3.day(dayOfWeek, {
            width: "short",
            context: "formatting"
          });
        case "eeee":
        default:
          return localize3.day(dayOfWeek, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    c: function c(date, token, localize3, options) {
      var dayOfWeek = date.getDay();
      var localDayOfWeek = (dayOfWeek - options.weekStartsOn + 8) % 7 || 7;
      switch (token) {
        case "c":
          return String(localDayOfWeek);
        case "cc":
          return addLeadingZeros(localDayOfWeek, token.length);
        case "co":
          return localize3.ordinalNumber(localDayOfWeek, { unit: "day" });
        case "ccc":
          return localize3.day(dayOfWeek, {
            width: "abbreviated",
            context: "standalone"
          });
        case "ccccc":
          return localize3.day(dayOfWeek, {
            width: "narrow",
            context: "standalone"
          });
        case "cccccc":
          return localize3.day(dayOfWeek, {
            width: "short",
            context: "standalone"
          });
        case "cccc":
        default:
          return localize3.day(dayOfWeek, {
            width: "wide",
            context: "standalone"
          });
      }
    },
    i: function i(date, token, localize3) {
      var dayOfWeek = date.getDay();
      var isoDayOfWeek = dayOfWeek === 0 ? 7 : dayOfWeek;
      switch (token) {
        case "i":
          return String(isoDayOfWeek);
        case "ii":
          return addLeadingZeros(isoDayOfWeek, token.length);
        case "io":
          return localize3.ordinalNumber(isoDayOfWeek, { unit: "day" });
        case "iii":
          return localize3.day(dayOfWeek, {
            width: "abbreviated",
            context: "formatting"
          });
        case "iiiii":
          return localize3.day(dayOfWeek, {
            width: "narrow",
            context: "formatting"
          });
        case "iiiiii":
          return localize3.day(dayOfWeek, {
            width: "short",
            context: "formatting"
          });
        case "iiii":
        default:
          return localize3.day(dayOfWeek, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    a: function a(date, token, localize3) {
      var hours = date.getHours();
      var dayPeriodEnumValue = hours / 12 >= 1 ? "pm" : "am";
      switch (token) {
        case "a":
        case "aa":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "abbreviated",
            context: "formatting"
          });
        case "aaa":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "abbreviated",
            context: "formatting"
          }).toLowerCase();
        case "aaaaa":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "narrow",
            context: "formatting"
          });
        case "aaaa":
        default:
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    b: function b(date, token, localize3) {
      var hours = date.getHours();
      var dayPeriodEnumValue;
      if (hours === 12) {
        dayPeriodEnumValue = dayPeriodEnum.noon;
      } else if (hours === 0) {
        dayPeriodEnumValue = dayPeriodEnum.midnight;
      } else {
        dayPeriodEnumValue = hours / 12 >= 1 ? "pm" : "am";
      }
      switch (token) {
        case "b":
        case "bb":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "abbreviated",
            context: "formatting"
          });
        case "bbb":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "abbreviated",
            context: "formatting"
          }).toLowerCase();
        case "bbbbb":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "narrow",
            context: "formatting"
          });
        case "bbbb":
        default:
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    B: function B(date, token, localize3) {
      var hours = date.getHours();
      var dayPeriodEnumValue;
      if (hours >= 17) {
        dayPeriodEnumValue = dayPeriodEnum.evening;
      } else if (hours >= 12) {
        dayPeriodEnumValue = dayPeriodEnum.afternoon;
      } else if (hours >= 4) {
        dayPeriodEnumValue = dayPeriodEnum.morning;
      } else {
        dayPeriodEnumValue = dayPeriodEnum.night;
      }
      switch (token) {
        case "B":
        case "BB":
        case "BBB":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "abbreviated",
            context: "formatting"
          });
        case "BBBBB":
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "narrow",
            context: "formatting"
          });
        case "BBBB":
        default:
          return localize3.dayPeriod(dayPeriodEnumValue, {
            width: "wide",
            context: "formatting"
          });
      }
    },
    h: function h(date, token, localize3) {
      if (token === "ho") {
        var hours = date.getHours() % 12;
        if (hours === 0)
        hours = 12;
        return localize3.ordinalNumber(hours, { unit: "hour" });
      }
      return _lightFormatters.h(date, token);
    },
    H: function H(date, token, localize3) {
      if (token === "Ho") {
        return localize3.ordinalNumber(date.getHours(), { unit: "hour" });
      }
      return _lightFormatters.H(date, token);
    },
    K: function K(date, token, localize3) {
      var hours = date.getHours() % 12;
      if (token === "Ko") {
        return localize3.ordinalNumber(hours, { unit: "hour" });
      }
      return addLeadingZeros(hours, token.length);
    },
    k: function k(date, token, localize3) {
      var hours = date.getHours();
      if (hours === 0)
      hours = 24;
      if (token === "ko") {
        return localize3.ordinalNumber(hours, { unit: "hour" });
      }
      return addLeadingZeros(hours, token.length);
    },
    m: function m(date, token, localize3) {
      if (token === "mo") {
        return localize3.ordinalNumber(date.getMinutes(), { unit: "minute" });
      }
      return _lightFormatters.m(date, token);
    },
    s: function s(date, token, localize3) {
      if (token === "so") {
        return localize3.ordinalNumber(date.getSeconds(), { unit: "second" });
      }
      return _lightFormatters.s(date, token);
    },
    S: function S(date, token) {
      return _lightFormatters.S(date, token);
    },
    X: function X(date, token, _localize) {
      var timezoneOffset = date.getTimezoneOffset();
      if (timezoneOffset === 0) {
        return "Z";
      }
      switch (token) {
        case "X":
          return formatTimezoneWithOptionalMinutes(timezoneOffset);
        case "XXXX":
        case "XX":
          return formatTimezone(timezoneOffset);
        case "XXXXX":
        case "XXX":
        default:
          return formatTimezone(timezoneOffset, ":");
      }
    },
    x: function x(date, token, _localize) {
      var timezoneOffset = date.getTimezoneOffset();
      switch (token) {
        case "x":
          return formatTimezoneWithOptionalMinutes(timezoneOffset);
        case "xxxx":
        case "xx":
          return formatTimezone(timezoneOffset);
        case "xxxxx":
        case "xxx":
        default:
          return formatTimezone(timezoneOffset, ":");
      }
    },
    O: function O(date, token, _localize) {
      var timezoneOffset = date.getTimezoneOffset();
      switch (token) {
        case "O":
        case "OO":
        case "OOO":
          return "GMT" + formatTimezoneShort(timezoneOffset, ":");
        case "OOOO":
        default:
          return "GMT" + formatTimezone(timezoneOffset, ":");
      }
    },
    z: function z(date, token, _localize) {
      var timezoneOffset = date.getTimezoneOffset();
      switch (token) {
        case "z":
        case "zz":
        case "zzz":
          return "GMT" + formatTimezoneShort(timezoneOffset, ":");
        case "zzzz":
        default:
          return "GMT" + formatTimezone(timezoneOffset, ":");
      }
    },
    t: function t(date, token, _localize) {
      var timestamp = Math.trunc(date.getTime() / 1000);
      return addLeadingZeros(timestamp, token.length);
    },
    T: function T(date, token, _localize) {
      var timestamp = date.getTime();
      return addLeadingZeros(timestamp, token.length);
    }
  };

  // lib/_lib/format/longFormatters.mjs
  var dateLongFormatter = function dateLongFormatter(pattern, formatLong3) {
    switch (pattern) {
      case "P":
        return formatLong3.date({ width: "short" });
      case "PP":
        return formatLong3.date({ width: "medium" });
      case "PPP":
        return formatLong3.date({ width: "long" });
      case "PPPP":
      default:
        return formatLong3.date({ width: "full" });
    }
  };
  var timeLongFormatter = function timeLongFormatter(pattern, formatLong3) {
    switch (pattern) {
      case "p":
        return formatLong3.time({ width: "short" });
      case "pp":
        return formatLong3.time({ width: "medium" });
      case "ppp":
        return formatLong3.time({ width: "long" });
      case "pppp":
      default:
        return formatLong3.time({ width: "full" });
    }
  };
  var dateTimeLongFormatter = function dateTimeLongFormatter(pattern, formatLong3) {
    var matchResult = pattern.match(/(P+)(p+)?/) || [];
    var datePattern = matchResult[1];
    var timePattern = matchResult[2];
    if (!timePattern) {
      return dateLongFormatter(pattern, formatLong3);
    }
    var dateTimeFormat;
    switch (datePattern) {
      case "P":
        dateTimeFormat = formatLong3.dateTime({ width: "short" });
        break;
      case "PP":
        dateTimeFormat = formatLong3.dateTime({ width: "medium" });
        break;
      case "PPP":
        dateTimeFormat = formatLong3.dateTime({ width: "long" });
        break;
      case "PPPP":
      default:
        dateTimeFormat = formatLong3.dateTime({ width: "full" });
        break;
    }
    return dateTimeFormat.replace("{{date}}", dateLongFormatter(datePattern, formatLong3)).replace("{{time}}", timeLongFormatter(timePattern, formatLong3));
  };
  var _longFormatters = {
    p: timeLongFormatter,
    P: dateTimeLongFormatter
  };

  // lib/_lib/protectedTokens.mjs
  function isProtectedDayOfYearToken(token) {
    return dayOfYearTokenRE.test(token);
  }
  function isProtectedWeekYearToken(token) {
    return weekYearTokenRE.test(token);
  }
  function warnOrThrowProtectedError(token, format, input) {
    var _message = message(token, format, input);
    console.warn(_message);
    if (throwTokens.includes(token))
    throw new RangeError(_message);
  }
  var message = function message(token, format, input) {
    var subject = token[0] === "Y" ? "years" : "days of the month";
    return "Use `".concat(token.toLowerCase(), "` instead of `").concat(token, "` (in `").concat(format, "`) for formatting ").concat(subject, " to the input `").concat(input, "`; see: https://github.com/date-fns/date-fns/blob/master/docs/unicodeTokens.md");
  };
  var dayOfYearTokenRE = /^D+$/;
  var weekYearTokenRE = /^Y+$/;
  var throwTokens = ["D", "DD", "YY", "YYYY"];

  // lib/format.mjs
  function _format(date, formatStr, options) {var _ref13, _options$locale5, _ref14, _ref15, _ref16, _options$firstWeekCon3, _options$locale6, _defaultOptions7$loca, _ref17, _ref18, _ref19, _options$weekStartsOn3, _options$locale7, _defaultOptions7$loca2;
    var defaultOptions7 = getDefaultOptions();
    var locale = (_ref13 = (_options$locale5 = options === null || options === void 0 ? void 0 : options.locale) !== null && _options$locale5 !== void 0 ? _options$locale5 : defaultOptions7.locale) !== null && _ref13 !== void 0 ? _ref13 : enUS;
    var firstWeekContainsDate = (_ref14 = (_ref15 = (_ref16 = (_options$firstWeekCon3 = options === null || options === void 0 ? void 0 : options.firstWeekContainsDate) !== null && _options$firstWeekCon3 !== void 0 ? _options$firstWeekCon3 : options === null || options === void 0 || (_options$locale6 = options.locale) === null || _options$locale6 === void 0 || (_options$locale6 = _options$locale6.options) === null || _options$locale6 === void 0 ? void 0 : _options$locale6.firstWeekContainsDate) !== null && _ref16 !== void 0 ? _ref16 : defaultOptions7.firstWeekContainsDate) !== null && _ref15 !== void 0 ? _ref15 : (_defaultOptions7$loca = defaultOptions7.locale) === null || _defaultOptions7$loca === void 0 || (_defaultOptions7$loca = _defaultOptions7$loca.options) === null || _defaultOptions7$loca === void 0 ? void 0 : _defaultOptions7$loca.firstWeekContainsDate) !== null && _ref14 !== void 0 ? _ref14 : 1;
    var weekStartsOn = (_ref17 = (_ref18 = (_ref19 = (_options$weekStartsOn3 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn3 !== void 0 ? _options$weekStartsOn3 : options === null || options === void 0 || (_options$locale7 = options.locale) === null || _options$locale7 === void 0 || (_options$locale7 = _options$locale7.options) === null || _options$locale7 === void 0 ? void 0 : _options$locale7.weekStartsOn) !== null && _ref19 !== void 0 ? _ref19 : defaultOptions7.weekStartsOn) !== null && _ref18 !== void 0 ? _ref18 : (_defaultOptions7$loca2 = defaultOptions7.locale) === null || _defaultOptions7$loca2 === void 0 || (_defaultOptions7$loca2 = _defaultOptions7$loca2.options) === null || _defaultOptions7$loca2 === void 0 ? void 0 : _defaultOptions7$loca2.weekStartsOn) !== null && _ref17 !== void 0 ? _ref17 : 0;
    var originalDate = _toDate(date);
    if (!_isValid(originalDate)) {
      throw new RangeError("Invalid time value");
    }
    var parts = formatStr.match(longFormattingTokensRegExp).map(function (substring) {
      var firstCharacter = substring[0];
      if (firstCharacter === "p" || firstCharacter === "P") {
        var longFormatter = _longFormatters[firstCharacter];
        return longFormatter(substring, locale.formatLong);
      }
      return substring;
    }).join("").match(formattingTokensRegExp).map(function (substring) {
      if (substring === "''") {
        return { isToken: false, value: "'" };
      }
      var firstCharacter = substring[0];
      if (firstCharacter === "'") {
        return { isToken: false, value: cleanEscapedString(substring) };
      }
      if (_formatters[firstCharacter]) {
        return { isToken: true, value: substring };
      }
      if (firstCharacter.match(unescapedLatinCharacterRegExp)) {
        throw new RangeError("Format string contains an unescaped latin alphabet character `" + firstCharacter + "`");
      }
      return { isToken: false, value: substring };
    });
    if (locale.localize.preprocessor) {
      parts = locale.localize.preprocessor(originalDate, parts);
    }
    var formatterOptions = {
      firstWeekContainsDate: firstWeekContainsDate,
      weekStartsOn: weekStartsOn,
      locale: locale
    };
    return parts.map(function (part) {
      if (!part.isToken)
      return part.value;
      var token = part.value;
      if (!(options !== null && options !== void 0 && options.useAdditionalWeekYearTokens) && isProtectedWeekYearToken(token) || !(options !== null && options !== void 0 && options.useAdditionalDayOfYearTokens) && isProtectedDayOfYearToken(token)) {
        warnOrThrowProtectedError(token, formatStr, String(date));
      }
      var formatter = _formatters[token[0]];
      return formatter(originalDate, token, locale.localize, formatterOptions);
    }).join("");
  }
  var cleanEscapedString = function cleanEscapedString(input) {
    var matched = input.match(escapedStringRegExp);
    if (!matched) {
      return input;
    }
    return matched[1].replace(doubleQuoteRegExp, "'");
  };
  var formattingTokensRegExp = /[yYQqMLwIdDecihHKkms]o|(\w)\1*|''|'(''|[^'])+('|$)|./g;
  var longFormattingTokensRegExp = /P+p+|P+|p+|''|'(''|[^'])+('|$)|./g;
  var escapedStringRegExp = /^'([^]*?)'?$/;
  var doubleQuoteRegExp = /''/g;
  var unescapedLatinCharacterRegExp = /[a-zA-Z]/;
  // lib/formatDistance.mjs
  function formatDistance3(date, baseDate, options) {var _ref20, _options$locale8;
    var defaultOptions8 = getDefaultOptions();
    var locale = (_ref20 = (_options$locale8 = options === null || options === void 0 ? void 0 : options.locale) !== null && _options$locale8 !== void 0 ? _options$locale8 : defaultOptions8.locale) !== null && _ref20 !== void 0 ? _ref20 : enUS;
    var minutesInAlmostTwoDays = 2520;
    var comparison = _compareAsc(date, baseDate);
    if (isNaN(comparison)) {
      throw new RangeError("Invalid time value");
    }
    var localizeOptions = Object.assign({}, options, {
      addSuffix: options === null || options === void 0 ? void 0 : options.addSuffix,
      comparison: comparison
    });
    var dateLeft;
    var dateRight;
    if (comparison > 0) {
      dateLeft = _toDate(baseDate);
      dateRight = _toDate(date);
    } else {
      dateLeft = _toDate(date);
      dateRight = _toDate(baseDate);
    }
    var seconds = _differenceInSeconds(dateRight, dateLeft);
    var offsetInSeconds = (getTimezoneOffsetInMilliseconds(dateRight) - getTimezoneOffsetInMilliseconds(dateLeft)) / 1000;
    var minutes = Math.round((seconds - offsetInSeconds) / 60);
    var months;
    if (minutes < 2) {
      if (options !== null && options !== void 0 && options.includeSeconds) {
        if (seconds < 5) {
          return locale.formatDistance("lessThanXSeconds", 5, localizeOptions);
        } else if (seconds < 10) {
          return locale.formatDistance("lessThanXSeconds", 10, localizeOptions);
        } else if (seconds < 20) {
          return locale.formatDistance("lessThanXSeconds", 20, localizeOptions);
        } else if (seconds < 40) {
          return locale.formatDistance("halfAMinute", 0, localizeOptions);
        } else if (seconds < 60) {
          return locale.formatDistance("lessThanXMinutes", 1, localizeOptions);
        } else {
          return locale.formatDistance("xMinutes", 1, localizeOptions);
        }
      } else {
        if (minutes === 0) {
          return locale.formatDistance("lessThanXMinutes", 1, localizeOptions);
        } else {
          return locale.formatDistance("xMinutes", minutes, localizeOptions);
        }
      }
    } else if (minutes < 45) {
      return locale.formatDistance("xMinutes", minutes, localizeOptions);
    } else if (minutes < 90) {
      return locale.formatDistance("aboutXHours", 1, localizeOptions);
    } else if (minutes < minutesInDay) {
      var hours = Math.round(minutes / 60);
      return locale.formatDistance("aboutXHours", hours, localizeOptions);
    } else if (minutes < minutesInAlmostTwoDays) {
      return locale.formatDistance("xDays", 1, localizeOptions);
    } else if (minutes < minutesInMonth) {
      var _days = Math.round(minutes / minutesInDay);
      return locale.formatDistance("xDays", _days, localizeOptions);
    } else if (minutes < minutesInMonth * 2) {
      months = Math.round(minutes / minutesInMonth);
      return locale.formatDistance("aboutXMonths", months, localizeOptions);
    }
    months = _differenceInMonths(dateRight, dateLeft);
    if (months < 12) {
      var nearestMonth = Math.round(minutes / minutesInMonth);
      return locale.formatDistance("xMonths", nearestMonth, localizeOptions);
    } else {
      var monthsSinceStartOfYear = months % 12;
      var years = Math.trunc(months / 12);
      if (monthsSinceStartOfYear < 3) {
        return locale.formatDistance("aboutXYears", years, localizeOptions);
      } else if (monthsSinceStartOfYear < 9) {
        return locale.formatDistance("overXYears", years, localizeOptions);
      } else {
        return locale.formatDistance("almostXYears", years + 1, localizeOptions);
      }
    }
  }
  // lib/formatDistanceStrict.mjs
  function _formatDistanceStrict(date, baseDate, options) {var _ref21, _options$locale9, _options$roundingMeth;
    var defaultOptions9 = getDefaultOptions();
    var locale = (_ref21 = (_options$locale9 = options === null || options === void 0 ? void 0 : options.locale) !== null && _options$locale9 !== void 0 ? _options$locale9 : defaultOptions9.locale) !== null && _ref21 !== void 0 ? _ref21 : enUS;
    var comparison = _compareAsc(date, baseDate);
    if (isNaN(comparison)) {
      throw new RangeError("Invalid time value");
    }
    var localizeOptions = Object.assign({}, options, {
      addSuffix: options === null || options === void 0 ? void 0 : options.addSuffix,
      comparison: comparison
    });
    var dateLeft;
    var dateRight;
    if (comparison > 0) {
      dateLeft = _toDate(baseDate);
      dateRight = _toDate(date);
    } else {
      dateLeft = _toDate(date);
      dateRight = _toDate(baseDate);
    }
    var roundingMethod = getRoundingMethod((_options$roundingMeth = options === null || options === void 0 ? void 0 : options.roundingMethod) !== null && _options$roundingMeth !== void 0 ? _options$roundingMeth : "round");
    var milliseconds = dateRight.getTime() - dateLeft.getTime();
    var minutes = milliseconds / millisecondsInMinute;
    var timezoneOffset = getTimezoneOffsetInMilliseconds(dateRight) - getTimezoneOffsetInMilliseconds(dateLeft);
    var dstNormalizedMinutes = (milliseconds - timezoneOffset) / millisecondsInMinute;
    var defaultUnit = options === null || options === void 0 ? void 0 : options.unit;
    var unit;
    if (!defaultUnit) {
      if (minutes < 1) {
        unit = "second";
      } else if (minutes < 60) {
        unit = "minute";
      } else if (minutes < minutesInDay) {
        unit = "hour";
      } else if (dstNormalizedMinutes < minutesInMonth) {
        unit = "day";
      } else if (dstNormalizedMinutes < minutesInYear) {
        unit = "month";
      } else {
        unit = "year";
      }
    } else {
      unit = defaultUnit;
    }
    if (unit === "second") {
      var seconds = roundingMethod(milliseconds / 1000);
      return locale.formatDistance("xSeconds", seconds, localizeOptions);
    } else if (unit === "minute") {
      var roundedMinutes = roundingMethod(minutes);
      return locale.formatDistance("xMinutes", roundedMinutes, localizeOptions);
    } else if (unit === "hour") {
      var hours = roundingMethod(minutes / 60);
      return locale.formatDistance("xHours", hours, localizeOptions);
    } else if (unit === "day") {
      var _days2 = roundingMethod(dstNormalizedMinutes / minutesInDay);
      return locale.formatDistance("xDays", _days2, localizeOptions);
    } else if (unit === "month") {
      var _months = roundingMethod(dstNormalizedMinutes / minutesInMonth);
      return _months === 12 && defaultUnit !== "month" ? locale.formatDistance("xYears", 1, localizeOptions) : locale.formatDistance("xMonths", _months, localizeOptions);
    } else {
      var years = roundingMethod(dstNormalizedMinutes / minutesInYear);
      return locale.formatDistance("xYears", years, localizeOptions);
    }
  }
  // lib/formatDistanceToNow.mjs
  function _formatDistanceToNow(date, options) {
    return formatDistance3(date, _constructNow(date), options);
  }
  // lib/formatDistanceToNowStrict.mjs
  function _formatDistanceToNowStrict(date, options) {
    return _formatDistanceStrict(date, _constructNow(date), options);
  }
  // lib/formatDuration.mjs
  function _formatDuration(duration, options) {var _ref22, _options$locale10, _options$format, _options$zero, _options$delimiter;
    var defaultOptions10 = getDefaultOptions();
    var locale = (_ref22 = (_options$locale10 = options === null || options === void 0 ? void 0 : options.locale) !== null && _options$locale10 !== void 0 ? _options$locale10 : defaultOptions10.locale) !== null && _ref22 !== void 0 ? _ref22 : enUS;
    var format2 = (_options$format = options === null || options === void 0 ? void 0 : options.format) !== null && _options$format !== void 0 ? _options$format : defaultFormat;
    var zero = (_options$zero = options === null || options === void 0 ? void 0 : options.zero) !== null && _options$zero !== void 0 ? _options$zero : false;
    var delimiter = (_options$delimiter = options === null || options === void 0 ? void 0 : options.delimiter) !== null && _options$delimiter !== void 0 ? _options$delimiter : " ";
    if (!locale.formatDistance) {
      return "";
    }
    var result = format2.reduce(function (acc, unit) {
      var token = "x".concat(unit.replace(/(^.)/, function (m) {return m.toUpperCase();}));
      var value = duration[unit];
      if (value !== undefined && (zero || duration[unit])) {
        return acc.concat(locale.formatDistance(token, value));
      }
      return acc;
    }, []).join(delimiter);
    return result;
  }
  var defaultFormat = [
  "years",
  "months",
  "weeks",
  "days",
  "hours",
  "minutes",
  "seconds"];

  // lib/formatISO.mjs
  function _formatISO2(date, options) {var _options$format2, _options$representati;
    var _date = _toDate(date);
    if (isNaN(_date.getTime())) {
      throw new RangeError("Invalid time value");
    }
    var format2 = (_options$format2 = options === null || options === void 0 ? void 0 : options.format) !== null && _options$format2 !== void 0 ? _options$format2 : "extended";
    var representation = (_options$representati = options === null || options === void 0 ? void 0 : options.representation) !== null && _options$representati !== void 0 ? _options$representati : "complete";
    var result = "";
    var tzOffset = "";
    var dateDelimiter = format2 === "extended" ? "-" : "";
    var timeDelimiter = format2 === "extended" ? ":" : "";
    if (representation !== "time") {
      var day = addLeadingZeros(_date.getDate(), 2);
      var month = addLeadingZeros(_date.getMonth() + 1, 2);
      var year = addLeadingZeros(_date.getFullYear(), 4);
      result = "".concat(year).concat(dateDelimiter).concat(month).concat(dateDelimiter).concat(day);
    }
    if (representation !== "date") {
      var offset = _date.getTimezoneOffset();
      if (offset !== 0) {
        var absoluteOffset = Math.abs(offset);
        var hourOffset = addLeadingZeros(Math.trunc(absoluteOffset / 60), 2);
        var minuteOffset = addLeadingZeros(absoluteOffset % 60, 2);
        var sign = offset < 0 ? "+" : "-";
        tzOffset = "".concat(sign).concat(hourOffset, ":").concat(minuteOffset);
      } else {
        tzOffset = "Z";
      }
      var hour = addLeadingZeros(_date.getHours(), 2);
      var minute = addLeadingZeros(_date.getMinutes(), 2);
      var second = addLeadingZeros(_date.getSeconds(), 2);
      var separator = result === "" ? "" : "T";
      var time = [hour, minute, second].join(timeDelimiter);
      result = "".concat(result).concat(separator).concat(time).concat(tzOffset);
    }
    return result;
  }
  // lib/formatISO9075.mjs
  function _formatISO(date, options) {var _options$format3, _options$representati2;
    var _date = _toDate(date);
    if (!_isValid(_date)) {
      throw new RangeError("Invalid time value");
    }
    var format2 = (_options$format3 = options === null || options === void 0 ? void 0 : options.format) !== null && _options$format3 !== void 0 ? _options$format3 : "extended";
    var representation = (_options$representati2 = options === null || options === void 0 ? void 0 : options.representation) !== null && _options$representati2 !== void 0 ? _options$representati2 : "complete";
    var result = "";
    var dateDelimiter = format2 === "extended" ? "-" : "";
    var timeDelimiter = format2 === "extended" ? ":" : "";
    if (representation !== "time") {
      var day = addLeadingZeros(_date.getDate(), 2);
      var month = addLeadingZeros(_date.getMonth() + 1, 2);
      var year = addLeadingZeros(_date.getFullYear(), 4);
      result = "".concat(year).concat(dateDelimiter).concat(month).concat(dateDelimiter).concat(day);
    }
    if (representation !== "date") {
      var hour = addLeadingZeros(_date.getHours(), 2);
      var minute = addLeadingZeros(_date.getMinutes(), 2);
      var second = addLeadingZeros(_date.getSeconds(), 2);
      var separator = result === "" ? "" : " ";
      result = "".concat(result).concat(separator).concat(hour).concat(timeDelimiter).concat(minute).concat(timeDelimiter).concat(second);
    }
    return result;
  }
  // lib/formatISODuration.mjs
  function _formatISODuration(duration) {
    var _duration$years2 =






      duration.years,years = _duration$years2 === void 0 ? 0 : _duration$years2,_duration$months2 = duration.months,months = _duration$months2 === void 0 ? 0 : _duration$months2,_duration$days2 = duration.days,days = _duration$days2 === void 0 ? 0 : _duration$days2,_duration$hours2 = duration.hours,hours = _duration$hours2 === void 0 ? 0 : _duration$hours2,_duration$minutes2 = duration.minutes,minutes = _duration$minutes2 === void 0 ? 0 : _duration$minutes2,_duration$seconds2 = duration.seconds,seconds = _duration$seconds2 === void 0 ? 0 : _duration$seconds2;
    return "P".concat(years, "Y").concat(months, "M").concat(days, "DT").concat(hours, "H").concat(minutes, "M").concat(seconds, "S");
  }
  // lib/formatRFC3339.mjs
  function _formatRFC2(date, options) {var _options$fractionDigi;
    var _date = _toDate(date);
    if (!_isValid(_date)) {
      throw new RangeError("Invalid time value");
    }
    var fractionDigits = (_options$fractionDigi = options === null || options === void 0 ? void 0 : options.fractionDigits) !== null && _options$fractionDigi !== void 0 ? _options$fractionDigi : 0;
    var day = addLeadingZeros(_date.getDate(), 2);
    var month = addLeadingZeros(_date.getMonth() + 1, 2);
    var year = _date.getFullYear();
    var hour = addLeadingZeros(_date.getHours(), 2);
    var minute = addLeadingZeros(_date.getMinutes(), 2);
    var second = addLeadingZeros(_date.getSeconds(), 2);
    var fractionalSecond = "";
    if (fractionDigits > 0) {
      var milliseconds = _date.getMilliseconds();
      var fractionalSeconds = Math.trunc(milliseconds * Math.pow(10, fractionDigits - 3));
      fractionalSecond = "." + addLeadingZeros(fractionalSeconds, fractionDigits);
    }
    var offset = "";
    var tzOffset = _date.getTimezoneOffset();
    if (tzOffset !== 0) {
      var absoluteOffset = Math.abs(tzOffset);
      var hourOffset = addLeadingZeros(Math.trunc(absoluteOffset / 60), 2);
      var minuteOffset = addLeadingZeros(absoluteOffset % 60, 2);
      var sign = tzOffset < 0 ? "+" : "-";
      offset = "".concat(sign).concat(hourOffset, ":").concat(minuteOffset);
    } else {
      offset = "Z";
    }
    return "".concat(year, "-").concat(month, "-").concat(day, "T").concat(hour, ":").concat(minute, ":").concat(second).concat(fractionalSecond).concat(offset);
  }
  // lib/formatRFC7231.mjs
  function _formatRFC(date) {
    var _date = _toDate(date);
    if (!_isValid(_date)) {
      throw new RangeError("Invalid time value");
    }
    var dayName = days[_date.getUTCDay()];
    var dayOfMonth = addLeadingZeros(_date.getUTCDate(), 2);
    var monthName = months[_date.getUTCMonth()];
    var year = _date.getUTCFullYear();
    var hour = addLeadingZeros(_date.getUTCHours(), 2);
    var minute = addLeadingZeros(_date.getUTCMinutes(), 2);
    var second = addLeadingZeros(_date.getUTCSeconds(), 2);
    return "".concat(dayName, ", ").concat(dayOfMonth, " ").concat(monthName, " ").concat(year, " ").concat(hour, ":").concat(minute, ":").concat(second, " GMT");
  }
  var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var months = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec"];

  // lib/formatRelative.mjs
  function formatRelative3(date, baseDate, options) {var _ref23, _options$locale11, _ref24, _ref25, _ref26, _options$weekStartsOn4, _options$locale12, _defaultOptions11$loc;
    var _date = _toDate(date);
    var _baseDate = _toDate(baseDate);
    var defaultOptions11 = getDefaultOptions();
    var locale = (_ref23 = (_options$locale11 = options === null || options === void 0 ? void 0 : options.locale) !== null && _options$locale11 !== void 0 ? _options$locale11 : defaultOptions11.locale) !== null && _ref23 !== void 0 ? _ref23 : enUS;
    var weekStartsOn = (_ref24 = (_ref25 = (_ref26 = (_options$weekStartsOn4 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn4 !== void 0 ? _options$weekStartsOn4 : options === null || options === void 0 || (_options$locale12 = options.locale) === null || _options$locale12 === void 0 || (_options$locale12 = _options$locale12.options) === null || _options$locale12 === void 0 ? void 0 : _options$locale12.weekStartsOn) !== null && _ref26 !== void 0 ? _ref26 : defaultOptions11.weekStartsOn) !== null && _ref25 !== void 0 ? _ref25 : (_defaultOptions11$loc = defaultOptions11.locale) === null || _defaultOptions11$loc === void 0 || (_defaultOptions11$loc = _defaultOptions11$loc.options) === null || _defaultOptions11$loc === void 0 ? void 0 : _defaultOptions11$loc.weekStartsOn) !== null && _ref24 !== void 0 ? _ref24 : 0;
    var diff = _differenceInCalendarDays(_date, _baseDate);
    if (isNaN(diff)) {
      throw new RangeError("Invalid time value");
    }
    var token;
    if (diff < -6) {
      token = "other";
    } else if (diff < -1) {
      token = "lastWeek";
    } else if (diff < 0) {
      token = "yesterday";
    } else if (diff < 1) {
      token = "today";
    } else if (diff < 2) {
      token = "tomorrow";
    } else if (diff < 7) {
      token = "nextWeek";
    } else {
      token = "other";
    }
    var formatStr = locale.formatRelative(token, _date, _baseDate, {
      locale: locale,
      weekStartsOn: weekStartsOn
    });
    return _format(_date, formatStr, { locale: locale, weekStartsOn: weekStartsOn });
  }
  // lib/fromUnixTime.mjs
  function _fromUnixTime(unixTime) {
    return _toDate(unixTime * 1000);
  }
  // lib/getDate.mjs
  function _getDate(date) {
    var _date = _toDate(date);
    var dayOfMonth = _date.getDate();
    return dayOfMonth;
  }
  // lib/getDay.mjs
  function _getDay(date) {
    var _date = _toDate(date);
    var day = _date.getDay();
    return day;
  }
  // lib/getDaysInMonth.mjs
  function _getDaysInMonth(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var monthIndex = _date.getMonth();
    var lastDayOfMonth = _constructFrom(date, 0);
    lastDayOfMonth.setFullYear(year, monthIndex + 1, 0);
    lastDayOfMonth.setHours(0, 0, 0, 0);
    return lastDayOfMonth.getDate();
  }
  // lib/isLeapYear.mjs
  function _isLeapYear(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    return year % 400 === 0 || year % 4 === 0 && year % 100 !== 0;
  }

  // lib/getDaysInYear.mjs
  function _getDaysInYear(date) {
    var _date = _toDate(date);
    if (String(new Date(_date)) === "Invalid Date") {
      return NaN;
    }
    return _isLeapYear(_date) ? 366 : 365;
  }
  // lib/getDecade.mjs
  function _getDecade(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var decade = Math.floor(year / 10) * 10;
    return decade;
  }
  // lib/getDefaultOptions.mjs
  function getDefaultOptions2() {
    return Object.assign({}, getDefaultOptions());
  }
  // lib/getHours.mjs
  function _getHours(date) {
    var _date = _toDate(date);
    var hours = _date.getHours();
    return hours;
  }
  // lib/getISODay.mjs
  function _getISODay(date) {
    var _date = _toDate(date);
    var day = _date.getDay();
    if (day === 0) {
      day = 7;
    }
    return day;
  }
  // lib/getISOWeeksInYear.mjs
  function _getISOWeeksInYear(date) {
    var thisYear = _startOfISOWeekYear(date);
    var nextYear = _startOfISOWeekYear(_addWeeks(thisYear, 60));
    var diff = +nextYear - +thisYear;
    return Math.round(diff / millisecondsInWeek);
  }
  // lib/getMilliseconds.mjs
  function _getMilliseconds(date) {
    var _date = _toDate(date);
    var milliseconds = _date.getMilliseconds();
    return milliseconds;
  }
  // lib/getMinutes.mjs
  function _getMinutes(date) {
    var _date = _toDate(date);
    var minutes = _date.getMinutes();
    return minutes;
  }
  // lib/getMonth.mjs
  function _getMonth(date) {
    var _date = _toDate(date);
    var month = _date.getMonth();
    return month;
  }
  // lib/getOverlappingDaysInIntervals.mjs
  function _getOverlappingDaysInIntervals(intervalLeft, intervalRight) {
    var _sort5 = [
      +_toDate(intervalLeft.start),
      +_toDate(intervalLeft.end)].
      sort(function (a, b) {return a - b;}),_sort6 = _slicedToArray(_sort5, 2),leftStart = _sort6[0],leftEnd = _sort6[1];
    var _sort7 = [
      +_toDate(intervalRight.start),
      +_toDate(intervalRight.end)].
      sort(function (a, b) {return a - b;}),_sort8 = _slicedToArray(_sort7, 2),rightStart = _sort8[0],rightEnd = _sort8[1];
    var isOverlapping = leftStart < rightEnd && rightStart < leftEnd;
    if (!isOverlapping)
    return 0;
    var overlapLeft = rightStart < leftStart ? leftStart : rightStart;
    var left = overlapLeft - getTimezoneOffsetInMilliseconds(overlapLeft);
    var overlapRight = rightEnd > leftEnd ? leftEnd : rightEnd;
    var right = overlapRight - getTimezoneOffsetInMilliseconds(overlapRight);
    return Math.ceil((right - left) / millisecondsInDay);
  }
  // lib/getSeconds.mjs
  function _getSeconds(date) {
    var _date = _toDate(date);
    var seconds = _date.getSeconds();
    return seconds;
  }
  // lib/getTime.mjs
  function _getTime(date) {
    var _date = _toDate(date);
    var timestamp = _date.getTime();
    return timestamp;
  }
  // lib/getUnixTime.mjs
  function _getUnixTime(date) {
    return Math.trunc(+_toDate(date) / 1000);
  }
  // lib/getWeekOfMonth.mjs
  function _getWeekOfMonth(date, options) {var _ref27, _ref28, _ref29, _options$weekStartsOn5, _options$locale13, _defaultOptions13$loc;
    var defaultOptions13 = getDefaultOptions();
    var weekStartsOn = (_ref27 = (_ref28 = (_ref29 = (_options$weekStartsOn5 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn5 !== void 0 ? _options$weekStartsOn5 : options === null || options === void 0 || (_options$locale13 = options.locale) === null || _options$locale13 === void 0 || (_options$locale13 = _options$locale13.options) === null || _options$locale13 === void 0 ? void 0 : _options$locale13.weekStartsOn) !== null && _ref29 !== void 0 ? _ref29 : defaultOptions13.weekStartsOn) !== null && _ref28 !== void 0 ? _ref28 : (_defaultOptions13$loc = defaultOptions13.locale) === null || _defaultOptions13$loc === void 0 || (_defaultOptions13$loc = _defaultOptions13$loc.options) === null || _defaultOptions13$loc === void 0 ? void 0 : _defaultOptions13$loc.weekStartsOn) !== null && _ref27 !== void 0 ? _ref27 : 0;
    var currentDayOfMonth = _getDate(date);
    if (isNaN(currentDayOfMonth))
    return NaN;
    var startWeekDay = _getDay(_startOfMonth(date));
    var lastDayOfFirstWeek = weekStartsOn - startWeekDay;
    if (lastDayOfFirstWeek <= 0)
    lastDayOfFirstWeek += 7;
    var remainingDaysAfterFirstWeek = currentDayOfMonth - lastDayOfFirstWeek;
    return Math.ceil(remainingDaysAfterFirstWeek / 7) + 1;
  }
  // lib/lastDayOfMonth.mjs
  function _lastDayOfMonth(date) {
    var _date = _toDate(date);
    var month = _date.getMonth();
    _date.setFullYear(_date.getFullYear(), month + 1, 0);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/getWeeksInMonth.mjs
  function _getWeeksInMonth(date, options) {
    return _differenceInCalendarWeeks(_lastDayOfMonth(date), _startOfMonth(date), options) + 1;
  }
  // lib/getYear.mjs
  function _getYear(date) {
    return _toDate(date).getFullYear();
  }
  // lib/hoursToMilliseconds.mjs
  function _hoursToMilliseconds(hours) {
    return Math.trunc(hours * millisecondsInHour);
  }
  // lib/hoursToMinutes.mjs
  function _hoursToMinutes(hours) {
    return Math.trunc(hours * minutesInHour);
  }
  // lib/hoursToSeconds.mjs
  function _hoursToSeconds(hours) {
    return Math.trunc(hours * secondsInHour);
  }
  // lib/interval.mjs
  function _interval(start, end, options) {
    var _start = _toDate(start);
    if (isNaN(+_start))
    throw new TypeError("Start date is invalid");
    var _end = _toDate(end);
    if (isNaN(+_end))
    throw new TypeError("End date is invalid");
    if (options !== null && options !== void 0 && options.assertPositive && +_start > +_end)
    throw new TypeError("End date must be after start date");
    return { start: _start, end: _end };
  }
  // lib/intervalToDuration.mjs
  function _intervalToDuration(interval2) {
    var start = _toDate(interval2.start);
    var end = _toDate(interval2.end);
    var duration = {};
    var years = _differenceInYears(end, start);
    if (years)
    duration.years = years;
    var remainingMonths = _add(start, { years: duration.years });
    var months2 = _differenceInMonths(end, remainingMonths);
    if (months2)
    duration.months = months2;
    var remainingDays = _add(remainingMonths, { months: duration.months });
    var days2 = _differenceInDays(end, remainingDays);
    if (days2)
    duration.days = days2;
    var remainingHours = _add(remainingDays, { days: duration.days });
    var hours = _differenceInHours(end, remainingHours);
    if (hours)
    duration.hours = hours;
    var remainingMinutes = _add(remainingHours, { hours: duration.hours });
    var minutes = _differenceInMinutes(end, remainingMinutes);
    if (minutes)
    duration.minutes = minutes;
    var remainingSeconds = _add(remainingMinutes, { minutes: duration.minutes });
    var seconds = _differenceInSeconds(end, remainingSeconds);
    if (seconds)
    duration.seconds = seconds;
    return duration;
  }
  // lib/intlFormat.mjs
  function _intlFormat(date, formatOrLocale, localeOptions) {var _localeOptions;
    var formatOptions;
    if (isFormatOptions(formatOrLocale)) {
      formatOptions = formatOrLocale;
    } else {
      localeOptions = formatOrLocale;
    }
    return new Intl.DateTimeFormat((_localeOptions = localeOptions) === null || _localeOptions === void 0 ? void 0 : _localeOptions.locale, formatOptions).format(_toDate(date));
  }
  var isFormatOptions = function isFormatOptions(opts) {
    return opts !== undefined && !("locale" in opts);
  };
  // lib/intlFormatDistance.mjs
  function _intlFormatDistance(date, baseDate, options) {
    var value = 0;
    var unit;
    var dateLeft = _toDate(date);
    var dateRight = _toDate(baseDate);
    if (!(options !== null && options !== void 0 && options.unit)) {
      var diffInSeconds = _differenceInSeconds(dateLeft, dateRight);
      if (Math.abs(diffInSeconds) < secondsInMinute) {
        value = _differenceInSeconds(dateLeft, dateRight);
        unit = "second";
      } else if (Math.abs(diffInSeconds) < secondsInHour) {
        value = _differenceInMinutes(dateLeft, dateRight);
        unit = "minute";
      } else if (Math.abs(diffInSeconds) < secondsInDay && Math.abs(_differenceInCalendarDays(dateLeft, dateRight)) < 1) {
        value = _differenceInHours(dateLeft, dateRight);
        unit = "hour";
      } else if (Math.abs(diffInSeconds) < secondsInWeek && (value = _differenceInCalendarDays(dateLeft, dateRight)) && Math.abs(value) < 7) {
        unit = "day";
      } else if (Math.abs(diffInSeconds) < secondsInMonth) {
        value = _differenceInCalendarWeeks(dateLeft, dateRight);
        unit = "week";
      } else if (Math.abs(diffInSeconds) < secondsInQuarter) {
        value = _differenceInCalendarMonths(dateLeft, dateRight);
        unit = "month";
      } else if (Math.abs(diffInSeconds) < secondsInYear) {
        if (_differenceInCalendarQuarters(dateLeft, dateRight) < 4) {
          value = _differenceInCalendarQuarters(dateLeft, dateRight);
          unit = "quarter";
        } else {
          value = _differenceInCalendarYears(dateLeft, dateRight);
          unit = "year";
        }
      } else {
        value = _differenceInCalendarYears(dateLeft, dateRight);
        unit = "year";
      }
    } else {
      unit = options === null || options === void 0 ? void 0 : options.unit;
      if (unit === "second") {
        value = _differenceInSeconds(dateLeft, dateRight);
      } else if (unit === "minute") {
        value = _differenceInMinutes(dateLeft, dateRight);
      } else if (unit === "hour") {
        value = _differenceInHours(dateLeft, dateRight);
      } else if (unit === "day") {
        value = _differenceInCalendarDays(dateLeft, dateRight);
      } else if (unit === "week") {
        value = _differenceInCalendarWeeks(dateLeft, dateRight);
      } else if (unit === "month") {
        value = _differenceInCalendarMonths(dateLeft, dateRight);
      } else if (unit === "quarter") {
        value = _differenceInCalendarQuarters(dateLeft, dateRight);
      } else if (unit === "year") {
        value = _differenceInCalendarYears(dateLeft, dateRight);
      }
    }
    var rtf = new Intl.RelativeTimeFormat(options === null || options === void 0 ? void 0 : options.locale, {
      localeMatcher: options === null || options === void 0 ? void 0 : options.localeMatcher,
      numeric: (options === null || options === void 0 ? void 0 : options.numeric) || "auto",
      style: options === null || options === void 0 ? void 0 : options.style
    });
    return rtf.format(value, unit);
  }
  // lib/isAfter.mjs
  function _isAfter(date, dateToCompare) {
    var _date = _toDate(date);
    var _dateToCompare = _toDate(dateToCompare);
    return _date.getTime() > _dateToCompare.getTime();
  }
  // lib/isBefore.mjs
  function _isBefore(date, dateToCompare) {
    var _date = _toDate(date);
    var _dateToCompare = _toDate(dateToCompare);
    return +_date < +_dateToCompare;
  }
  // lib/isEqual.mjs
  function _isEqual(leftDate, rightDate) {
    var _dateLeft = _toDate(leftDate);
    var _dateRight = _toDate(rightDate);
    return +_dateLeft === +_dateRight;
  }
  // lib/isExists.mjs
  function _isExists(year, month, day) {
    var date = new Date(year, month, day);
    return date.getFullYear() === year && date.getMonth() === month && date.getDate() === day;
  }
  // lib/isFirstDayOfMonth.mjs
  function _isFirstDayOfMonth(date) {
    return _toDate(date).getDate() === 1;
  }
  // lib/isFriday.mjs
  function _isFriday(date) {
    return _toDate(date).getDay() === 5;
  }
  // lib/isFuture.mjs
  function _isFuture(date) {
    return +_toDate(date) > Date.now();
  }
  // lib/transpose.mjs
  function _transpose(fromDate, constructor) {
    var date = constructor instanceof Date ? _constructFrom(constructor, 0) : new constructor(0);
    date.setFullYear(fromDate.getFullYear(), fromDate.getMonth(), fromDate.getDate());
    date.setHours(fromDate.getHours(), fromDate.getMinutes(), fromDate.getSeconds(), fromDate.getMilliseconds());
    return date;
  }

  // lib/parse/_lib/Setter.mjs
  var TIMEZONE_UNIT_PRIORITY = 10;var

  Setter = /*#__PURE__*/function () {function Setter() {_classCallCheck(this, Setter);_defineProperty(this, "subPriority",
      0);}_createClass(Setter, [{ key: "validate", value:
      function validate(_utcDate, _options) {
        return true;
      } }]);return Setter;}();var


  ValueSetter = /*#__PURE__*/function (_Setter2) {_inherits(ValueSetter, _Setter2);
    function ValueSetter(value, validateValue, setValue, priority, subPriority) {var _this;_classCallCheck(this, ValueSetter);
      _this = _callSuper(this, ValueSetter);
      _this.value = value;
      _this.validateValue = validateValue;
      _this.setValue = setValue;
      _this.priority = priority;
      if (subPriority) {
        _this.subPriority = subPriority;
      }return _this;
    }_createClass(ValueSetter, [{ key: "validate", value:
      function validate(date, options) {
        return this.validateValue(date, this.value, options);
      } }, { key: "set", value:
      function set(date, flags, options) {
        return this.setValue(date, flags, this.value, options);
      } }]);return ValueSetter;}(Setter);var


  DateToSystemTimezoneSetter = /*#__PURE__*/function (_Setter3) {_inherits(DateToSystemTimezoneSetter, _Setter3);function DateToSystemTimezoneSetter() {var _this2;_classCallCheck(this, DateToSystemTimezoneSetter);for (var _len = arguments.length, args = new Array(_len), _key = 0; _key < _len; _key++) {args[_key] = arguments[_key];}_this2 = _callSuper(this, DateToSystemTimezoneSetter, [].concat(args));_defineProperty(_assertThisInitialized(_this2), "priority",
      TIMEZONE_UNIT_PRIORITY);_defineProperty(_assertThisInitialized(_this2), "subPriority",
      -1);return _this2;}_createClass(DateToSystemTimezoneSetter, [{ key: "set", value:
      function set(date, flags) {
        if (flags.timestampIsSet)
        return date;
        return _constructFrom(date, _transpose(date, Date));
      } }]);return DateToSystemTimezoneSetter;}(Setter);


  // lib/parse/_lib/Parser.mjs
  var Parser = /*#__PURE__*/function () {function Parser() {_classCallCheck(this, Parser);}_createClass(Parser, [{ key: "run", value:
      function run(dateString, token, match3, options) {
        var result = this.parse(dateString, token, match3, options);
        if (!result) {
          return null;
        }
        return {
          setter: new ValueSetter(result.value, this.validate, this.set, this.priority, this.subPriority),
          rest: result.rest
        };
      } }, { key: "validate", value:
      function validate(_utcDate, _value, _options) {
        return true;
      } }]);return Parser;}();


  // lib/parse/_lib/parsers/EraParser.mjs
  var EraParser = /*#__PURE__*/function (_Parser) {_inherits(EraParser, _Parser);function EraParser() {var _this3;_classCallCheck(this, EraParser);for (var _len2 = arguments.length, args = new Array(_len2), _key2 = 0; _key2 < _len2; _key2++) {args[_key2] = arguments[_key2];}_this3 = _callSuper(this, EraParser, [].concat(args));_defineProperty(_assertThisInitialized(_this3), "priority",
      140);_defineProperty(_assertThisInitialized(_this3), "incompatibleTokens",



















      ["R", "u", "t", "T"]);return _this3;}_createClass(EraParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "G":case "GG":case "GGG":return match3.era(dateString, { width: "abbreviated" }) || match3.era(dateString, { width: "narrow" });case "GGGGG":return match3.era(dateString, { width: "narrow" });case "GGGG":default:return match3.era(dateString, { width: "wide" }) || match3.era(dateString, { width: "abbreviated" }) || match3.era(dateString, { width: "narrow" });}} }, { key: "set", value: function set(date, flags, value) {flags.era = value;date.setFullYear(value, 0, 1);date.setHours(0, 0, 0, 0);return date;} }]);return EraParser;}(Parser);


  // lib/parse/_lib/constants.mjs
  var numericPatterns = {
    month: /^(1[0-2]|0?\d)/,
    date: /^(3[0-1]|[0-2]?\d)/,
    dayOfYear: /^(36[0-6]|3[0-5]\d|[0-2]?\d?\d)/,
    week: /^(5[0-3]|[0-4]?\d)/,
    hour23h: /^(2[0-3]|[0-1]?\d)/,
    hour24h: /^(2[0-4]|[0-1]?\d)/,
    hour11h: /^(1[0-1]|0?\d)/,
    hour12h: /^(1[0-2]|0?\d)/,
    minute: /^[0-5]?\d/,
    second: /^[0-5]?\d/,
    singleDigit: /^\d/,
    twoDigits: /^\d{1,2}/,
    threeDigits: /^\d{1,3}/,
    fourDigits: /^\d{1,4}/,
    anyDigitsSigned: /^-?\d+/,
    singleDigitSigned: /^-?\d/,
    twoDigitsSigned: /^-?\d{1,2}/,
    threeDigitsSigned: /^-?\d{1,3}/,
    fourDigitsSigned: /^-?\d{1,4}/
  };
  var timezonePatterns = {
    basicOptionalMinutes: /^([+-])(\d{2})(\d{2})?|Z/,
    basic: /^([+-])(\d{2})(\d{2})|Z/,
    basicOptionalSeconds: /^([+-])(\d{2})(\d{2})((\d{2}))?|Z/,
    extended: /^([+-])(\d{2}):(\d{2})|Z/,
    extendedOptionalSeconds: /^([+-])(\d{2}):(\d{2})(:(\d{2}))?|Z/
  };

  // lib/parse/_lib/utils.mjs
  function mapValue(parseFnResult, mapFn) {
    if (!parseFnResult) {
      return parseFnResult;
    }
    return {
      value: mapFn(parseFnResult.value),
      rest: parseFnResult.rest
    };
  }
  function parseNumericPattern(pattern, dateString) {
    var matchResult = dateString.match(pattern);
    if (!matchResult) {
      return null;
    }
    return {
      value: parseInt(matchResult[0], 10),
      rest: dateString.slice(matchResult[0].length)
    };
  }
  function parseTimezonePattern(pattern, dateString) {
    var matchResult = dateString.match(pattern);
    if (!matchResult) {
      return null;
    }
    if (matchResult[0] === "Z") {
      return {
        value: 0,
        rest: dateString.slice(1)
      };
    }
    var sign = matchResult[1] === "+" ? 1 : -1;
    var hours = matchResult[2] ? parseInt(matchResult[2], 10) : 0;
    var minutes = matchResult[3] ? parseInt(matchResult[3], 10) : 0;
    var seconds = matchResult[5] ? parseInt(matchResult[5], 10) : 0;
    return {
      value: sign * (hours * millisecondsInHour + minutes * millisecondsInMinute + seconds * millisecondsInSecond),
      rest: dateString.slice(matchResult[0].length)
    };
  }
  function parseAnyDigitsSigned(dateString) {
    return parseNumericPattern(numericPatterns.anyDigitsSigned, dateString);
  }
  function parseNDigits(n, dateString) {
    switch (n) {
      case 1:
        return parseNumericPattern(numericPatterns.singleDigit, dateString);
      case 2:
        return parseNumericPattern(numericPatterns.twoDigits, dateString);
      case 3:
        return parseNumericPattern(numericPatterns.threeDigits, dateString);
      case 4:
        return parseNumericPattern(numericPatterns.fourDigits, dateString);
      default:
        return parseNumericPattern(new RegExp("^\\d{1," + n + "}"), dateString);
    }
  }
  function parseNDigitsSigned(n, dateString) {
    switch (n) {
      case 1:
        return parseNumericPattern(numericPatterns.singleDigitSigned, dateString);
      case 2:
        return parseNumericPattern(numericPatterns.twoDigitsSigned, dateString);
      case 3:
        return parseNumericPattern(numericPatterns.threeDigitsSigned, dateString);
      case 4:
        return parseNumericPattern(numericPatterns.fourDigitsSigned, dateString);
      default:
        return parseNumericPattern(new RegExp("^-?\\d{1," + n + "}"), dateString);
    }
  }
  function dayPeriodEnumToHours(dayPeriod) {
    switch (dayPeriod) {
      case "morning":
        return 4;
      case "evening":
        return 17;
      case "pm":
      case "noon":
      case "afternoon":
        return 12;
      case "am":
      case "midnight":
      case "night":
      default:
        return 0;
    }
  }
  function normalizeTwoDigitYear(twoDigitYear, currentYear) {
    var isCommonEra = currentYear > 0;
    var absCurrentYear = isCommonEra ? currentYear : 1 - currentYear;
    var result;
    if (absCurrentYear <= 50) {
      result = twoDigitYear || 100;
    } else {
      var rangeEnd = absCurrentYear + 50;
      var rangeEndCentury = Math.trunc(rangeEnd / 100) * 100;
      var isPreviousCentury = twoDigitYear >= rangeEnd % 100;
      result = twoDigitYear + rangeEndCentury - (isPreviousCentury ? 100 : 0);
    }
    return isCommonEra ? result : 1 - result;
  }
  function isLeapYearIndex(year) {
    return year % 400 === 0 || year % 4 === 0 && year % 100 !== 0;
  }

  // lib/parse/_lib/parsers/YearParser.mjs
  var YearParser = /*#__PURE__*/function (_Parser2) {_inherits(YearParser, _Parser2);function YearParser() {var _this4;_classCallCheck(this, YearParser);for (var _len3 = arguments.length, args = new Array(_len3), _key3 = 0; _key3 < _len3; _key3++) {args[_key3] = arguments[_key3];}_this4 = _callSuper(this, YearParser, [].concat(args));_defineProperty(_assertThisInitialized(_this4), "priority",
      130);_defineProperty(_assertThisInitialized(_this4), "incompatibleTokens",
      ["Y", "R", "u", "w", "I", "i", "e", "c", "t", "T"]);return _this4;}_createClass(YearParser, [{ key: "parse", value:
      function parse(dateString, token, match3) {
        var valueCallback = function valueCallback(year) {return {
            year: year,
            isTwoDigitYear: token === "yy"
          };};
        switch (token) {
          case "y":
            return mapValue(parseNDigits(4, dateString), valueCallback);
          case "yo":
            return mapValue(match3.ordinalNumber(dateString, {
              unit: "year"
            }), valueCallback);
          default:
            return mapValue(parseNDigits(token.length, dateString), valueCallback);
        }
      } }, { key: "validate", value:
      function validate(_date, value) {
        return value.isTwoDigitYear || value.year > 0;
      } }, { key: "set", value:
      function set(date, flags, value) {
        var currentYear = date.getFullYear();
        if (value.isTwoDigitYear) {
          var normalizedTwoDigitYear = normalizeTwoDigitYear(value.year, currentYear);
          date.setFullYear(normalizedTwoDigitYear, 0, 1);
          date.setHours(0, 0, 0, 0);
          return date;
        }
        var year = !("era" in flags) || flags.era === 1 ? value.year : 1 - value.year;
        date.setFullYear(year, 0, 1);
        date.setHours(0, 0, 0, 0);
        return date;
      } }]);return YearParser;}(Parser);


  // lib/parse/_lib/parsers/LocalWeekYearParser.mjs
  var LocalWeekYearParser = /*#__PURE__*/function (_Parser3) {_inherits(LocalWeekYearParser, _Parser3);function LocalWeekYearParser() {var _this5;_classCallCheck(this, LocalWeekYearParser);for (var _len4 = arguments.length, args = new Array(_len4), _key4 = 0; _key4 < _len4; _key4++) {args[_key4] = arguments[_key4];}_this5 = _callSuper(this, LocalWeekYearParser, [].concat(args));_defineProperty(_assertThisInitialized(_this5), "priority",
      130);_defineProperty(_assertThisInitialized(_this5), "incompatibleTokens",
































      [
      "y",
      "R",
      "u",
      "Q",
      "q",
      "M",
      "L",
      "I",
      "d",
      "D",
      "i",
      "t",
      "T"]);return _this5;}_createClass(LocalWeekYearParser, [{ key: "parse", value: function parse(dateString, token, match3) {var valueCallback = function valueCallback(year) {return { year: year, isTwoDigitYear: token === "YY" };};switch (token) {case "Y":return mapValue(parseNDigits(4, dateString), valueCallback);case "Yo":return mapValue(match3.ordinalNumber(dateString, { unit: "year" }), valueCallback);default:return mapValue(parseNDigits(token.length, dateString), valueCallback);}} }, { key: "validate", value: function validate(_date, value) {return value.isTwoDigitYear || value.year > 0;} }, { key: "set", value: function set(date, flags, value, options) {var currentYear = _getWeekYear(date, options);if (value.isTwoDigitYear) {var normalizedTwoDigitYear = normalizeTwoDigitYear(value.year, currentYear);date.setFullYear(normalizedTwoDigitYear, 0, options.firstWeekContainsDate);date.setHours(0, 0, 0, 0);return _startOfWeek(date, options);}var year = !("era" in flags) || flags.era === 1 ? value.year : 1 - value.year;date.setFullYear(year, 0, options.firstWeekContainsDate);date.setHours(0, 0, 0, 0);return _startOfWeek(date, options);} }]);return LocalWeekYearParser;}(Parser);



  // lib/parse/_lib/parsers/ISOWeekYearParser.mjs
  var ISOWeekYearParser = /*#__PURE__*/function (_Parser4) {_inherits(ISOWeekYearParser, _Parser4);function ISOWeekYearParser() {var _this6;_classCallCheck(this, ISOWeekYearParser);for (var _len5 = arguments.length, args = new Array(_len5), _key5 = 0; _key5 < _len5; _key5++) {args[_key5] = arguments[_key5];}_this6 = _callSuper(this, ISOWeekYearParser, [].concat(args));_defineProperty(_assertThisInitialized(_this6), "priority",
      130);_defineProperty(_assertThisInitialized(_this6), "incompatibleTokens",












      [
      "G",
      "y",
      "Y",
      "u",
      "Q",
      "q",
      "M",
      "L",
      "w",
      "d",
      "D",
      "e",
      "c",
      "t",
      "T"]);return _this6;}_createClass(ISOWeekYearParser, [{ key: "parse", value: function parse(dateString, token) {if (token === "R") {return parseNDigitsSigned(4, dateString);}return parseNDigitsSigned(token.length, dateString);} }, { key: "set", value: function set(date, _flags, value) {var firstWeekOfYear = _constructFrom(date, 0);firstWeekOfYear.setFullYear(value, 0, 4);firstWeekOfYear.setHours(0, 0, 0, 0);return _startOfISOWeek(firstWeekOfYear);} }]);return ISOWeekYearParser;}(Parser);



  // lib/parse/_lib/parsers/ExtendedYearParser.mjs
  var ExtendedYearParser = /*#__PURE__*/function (_Parser5) {_inherits(ExtendedYearParser, _Parser5);function ExtendedYearParser() {var _this7;_classCallCheck(this, ExtendedYearParser);for (var _len6 = arguments.length, args = new Array(_len6), _key6 = 0; _key6 < _len6; _key6++) {args[_key6] = arguments[_key6];}_this7 = _callSuper(this, ExtendedYearParser, [].concat(args));_defineProperty(_assertThisInitialized(_this7), "priority",
      130);_defineProperty(_assertThisInitialized(_this7), "incompatibleTokens",











      ["G", "y", "Y", "R", "w", "I", "i", "e", "c", "t", "T"]);return _this7;}_createClass(ExtendedYearParser, [{ key: "parse", value: function parse(dateString, token) {if (token === "u") {return parseNDigitsSigned(4, dateString);}return parseNDigitsSigned(token.length, dateString);} }, { key: "set", value: function set(date, _flags, value) {date.setFullYear(value, 0, 1);date.setHours(0, 0, 0, 0);return date;} }]);return ExtendedYearParser;}(Parser);


  // lib/parse/_lib/parsers/QuarterParser.mjs
  var QuarterParser = /*#__PURE__*/function (_Parser6) {_inherits(QuarterParser, _Parser6);function QuarterParser() {var _this8;_classCallCheck(this, QuarterParser);for (var _len7 = arguments.length, args = new Array(_len7), _key7 = 0; _key7 < _len7; _key7++) {args[_key7] = arguments[_key7];}_this8 = _callSuper(this, QuarterParser, [].concat(args));_defineProperty(_assertThisInitialized(_this8), "priority",
      120);_defineProperty(_assertThisInitialized(_this8), "incompatibleTokens",










































      [
      "Y",
      "R",
      "q",
      "M",
      "L",
      "w",
      "I",
      "d",
      "D",
      "i",
      "e",
      "c",
      "t",
      "T"]);return _this8;}_createClass(QuarterParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "Q":case "QQ":return parseNDigits(token.length, dateString);case "Qo":return match3.ordinalNumber(dateString, { unit: "quarter" });case "QQQ":return match3.quarter(dateString, { width: "abbreviated", context: "formatting" }) || match3.quarter(dateString, { width: "narrow", context: "formatting" });case "QQQQQ":return match3.quarter(dateString, { width: "narrow", context: "formatting" });case "QQQQ":default:return match3.quarter(dateString, { width: "wide", context: "formatting" }) || match3.quarter(dateString, { width: "abbreviated", context: "formatting" }) || match3.quarter(dateString, { width: "narrow", context: "formatting" });}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 4;} }, { key: "set", value: function set(date, _flags, value) {date.setMonth((value - 1) * 3, 1);date.setHours(0, 0, 0, 0);return date;} }]);return QuarterParser;}(Parser);



  // lib/parse/_lib/parsers/StandAloneQuarterParser.mjs
  var StandAloneQuarterParser = /*#__PURE__*/function (_Parser7) {_inherits(StandAloneQuarterParser, _Parser7);function StandAloneQuarterParser() {var _this9;_classCallCheck(this, StandAloneQuarterParser);for (var _len8 = arguments.length, args = new Array(_len8), _key8 = 0; _key8 < _len8; _key8++) {args[_key8] = arguments[_key8];}_this9 = _callSuper(this, StandAloneQuarterParser, [].concat(args));_defineProperty(_assertThisInitialized(_this9), "priority",
      120);_defineProperty(_assertThisInitialized(_this9), "incompatibleTokens",










































      [
      "Y",
      "R",
      "Q",
      "M",
      "L",
      "w",
      "I",
      "d",
      "D",
      "i",
      "e",
      "c",
      "t",
      "T"]);return _this9;}_createClass(StandAloneQuarterParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "q":case "qq":return parseNDigits(token.length, dateString);case "qo":return match3.ordinalNumber(dateString, { unit: "quarter" });case "qqq":return match3.quarter(dateString, { width: "abbreviated", context: "standalone" }) || match3.quarter(dateString, { width: "narrow", context: "standalone" });case "qqqqq":return match3.quarter(dateString, { width: "narrow", context: "standalone" });case "qqqq":default:return match3.quarter(dateString, { width: "wide", context: "standalone" }) || match3.quarter(dateString, { width: "abbreviated", context: "standalone" }) || match3.quarter(dateString, { width: "narrow", context: "standalone" });}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 4;} }, { key: "set", value: function set(date, _flags, value) {date.setMonth((value - 1) * 3, 1);date.setHours(0, 0, 0, 0);return date;} }]);return StandAloneQuarterParser;}(Parser);



  // lib/parse/_lib/parsers/MonthParser.mjs
  var MonthParser = /*#__PURE__*/function (_Parser8) {_inherits(MonthParser, _Parser8);function MonthParser() {var _this10;_classCallCheck(this, MonthParser);for (var _len9 = arguments.length, args = new Array(_len9), _key9 = 0; _key9 < _len9; _key9++) {args[_key9] = arguments[_key9];}_this10 = _callSuper(this, MonthParser, [].concat(args));_defineProperty(_assertThisInitialized(_this10), "incompatibleTokens",
      [
      "Y",
      "R",
      "q",
      "Q",
      "L",
      "w",
      "I",
      "D",
      "i",
      "e",
      "c",
      "t",
      "T"]);_defineProperty(_assertThisInitialized(_this10), "priority",

      110);return _this10;}_createClass(MonthParser, [{ key: "parse", value:
      function parse(dateString, token, match3) {
        var valueCallback = function valueCallback(value) {return value - 1;};
        switch (token) {
          case "M":
            return mapValue(parseNumericPattern(numericPatterns.month, dateString), valueCallback);
          case "MM":
            return mapValue(parseNDigits(2, dateString), valueCallback);
          case "Mo":
            return mapValue(match3.ordinalNumber(dateString, {
              unit: "month"
            }), valueCallback);
          case "MMM":
            return match3.month(dateString, {
              width: "abbreviated",
              context: "formatting"
            }) || match3.month(dateString, { width: "narrow", context: "formatting" });
          case "MMMMM":
            return match3.month(dateString, {
              width: "narrow",
              context: "formatting"
            });
          case "MMMM":
          default:
            return match3.month(dateString, { width: "wide", context: "formatting" }) || match3.month(dateString, {
              width: "abbreviated",
              context: "formatting"
            }) || match3.month(dateString, { width: "narrow", context: "formatting" });
        }
      } }, { key: "validate", value:
      function validate(_date, value) {
        return value >= 0 && value <= 11;
      } }, { key: "set", value:
      function set(date, _flags, value) {
        date.setMonth(value, 1);
        date.setHours(0, 0, 0, 0);
        return date;
      } }]);return MonthParser;}(Parser);


  // lib/parse/_lib/parsers/StandAloneMonthParser.mjs
  var StandAloneMonthParser = /*#__PURE__*/function (_Parser9) {_inherits(StandAloneMonthParser, _Parser9);function StandAloneMonthParser() {var _this11;_classCallCheck(this, StandAloneMonthParser);for (var _len10 = arguments.length, args = new Array(_len10), _key10 = 0; _key10 < _len10; _key10++) {args[_key10] = arguments[_key10];}_this11 = _callSuper(this, StandAloneMonthParser, [].concat(args));_defineProperty(_assertThisInitialized(_this11), "priority",
      110);_defineProperty(_assertThisInitialized(_this11), "incompatibleTokens",





































      [
      "Y",
      "R",
      "q",
      "Q",
      "M",
      "w",
      "I",
      "D",
      "i",
      "e",
      "c",
      "t",
      "T"]);return _this11;}_createClass(StandAloneMonthParser, [{ key: "parse", value: function parse(dateString, token, match3) {var valueCallback = function valueCallback(value) {return value - 1;};switch (token) {case "L":return mapValue(parseNumericPattern(numericPatterns.month, dateString), valueCallback);case "LL":return mapValue(parseNDigits(2, dateString), valueCallback);case "Lo":return mapValue(match3.ordinalNumber(dateString, { unit: "month" }), valueCallback);case "LLL":return match3.month(dateString, { width: "abbreviated", context: "standalone" }) || match3.month(dateString, { width: "narrow", context: "standalone" });case "LLLLL":return match3.month(dateString, { width: "narrow", context: "standalone" });case "LLLL":default:return match3.month(dateString, { width: "wide", context: "standalone" }) || match3.month(dateString, { width: "abbreviated", context: "standalone" }) || match3.month(dateString, { width: "narrow", context: "standalone" });}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 11;} }, { key: "set", value: function set(date, _flags, value) {date.setMonth(value, 1);date.setHours(0, 0, 0, 0);return date;} }]);return StandAloneMonthParser;}(Parser);



  // lib/setWeek.mjs
  function _setWeek(date, week, options) {
    var _date = _toDate(date);
    var diff = _getWeek(_date, options) - week;
    _date.setDate(_date.getDate() - diff * 7);
    return _date;
  }

  // lib/parse/_lib/parsers/LocalWeekParser.mjs
  var LocalWeekParser = /*#__PURE__*/function (_Parser10) {_inherits(LocalWeekParser, _Parser10);function LocalWeekParser() {var _this12;_classCallCheck(this, LocalWeekParser);for (var _len11 = arguments.length, args = new Array(_len11), _key11 = 0; _key11 < _len11; _key11++) {args[_key11] = arguments[_key11];}_this12 = _callSuper(this, LocalWeekParser, [].concat(args));_defineProperty(_assertThisInitialized(_this12), "priority",
      100);_defineProperty(_assertThisInitialized(_this12), "incompatibleTokens",
















      [
      "y",
      "R",
      "u",
      "q",
      "Q",
      "M",
      "L",
      "I",
      "d",
      "D",
      "i",
      "t",
      "T"]);return _this12;}_createClass(LocalWeekParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "w":return parseNumericPattern(numericPatterns.week, dateString);case "wo":return match3.ordinalNumber(dateString, { unit: "week" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 53;} }, { key: "set", value: function set(date, _flags, value, options) {return _startOfWeek(_setWeek(date, value, options), options);} }]);return LocalWeekParser;}(Parser);



  // lib/setISOWeek.mjs
  function _setISOWeek(date, week) {
    var _date = _toDate(date);
    var diff = _getISOWeek(_date) - week;
    _date.setDate(_date.getDate() - diff * 7);
    return _date;
  }

  // lib/parse/_lib/parsers/ISOWeekParser.mjs
  var ISOWeekParser = /*#__PURE__*/function (_Parser11) {_inherits(ISOWeekParser, _Parser11);function ISOWeekParser() {var _this13;_classCallCheck(this, ISOWeekParser);for (var _len12 = arguments.length, args = new Array(_len12), _key12 = 0; _key12 < _len12; _key12++) {args[_key12] = arguments[_key12];}_this13 = _callSuper(this, ISOWeekParser, [].concat(args));_defineProperty(_assertThisInitialized(_this13), "priority",
      100);_defineProperty(_assertThisInitialized(_this13), "incompatibleTokens",
















      [
      "y",
      "Y",
      "u",
      "q",
      "Q",
      "M",
      "L",
      "w",
      "d",
      "D",
      "e",
      "c",
      "t",
      "T"]);return _this13;}_createClass(ISOWeekParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "I":return parseNumericPattern(numericPatterns.week, dateString);case "Io":return match3.ordinalNumber(dateString, { unit: "week" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 53;} }, { key: "set", value: function set(date, _flags, value) {return _startOfISOWeek(_setISOWeek(date, value));} }]);return ISOWeekParser;}(Parser);



  // lib/parse/_lib/parsers/DateParser.mjs
  var DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  var DAYS_IN_MONTH_LEAP_YEAR = [
  31,
  29,
  31,
  30,
  31,
  30,
  31,
  31,
  30,
  31,
  30,
  31];var


  DateParser = /*#__PURE__*/function (_Parser12) {_inherits(DateParser, _Parser12);function DateParser() {var _this14;_classCallCheck(this, DateParser);for (var _len13 = arguments.length, args = new Array(_len13), _key13 = 0; _key13 < _len13; _key13++) {args[_key13] = arguments[_key13];}_this14 = _callSuper(this, DateParser, [].concat(args));_defineProperty(_assertThisInitialized(_this14), "priority",
      90);_defineProperty(_assertThisInitialized(_this14), "subPriority",
      1);_defineProperty(_assertThisInitialized(_this14), "incompatibleTokens",

























      [
      "Y",
      "R",
      "q",
      "Q",
      "w",
      "I",
      "D",
      "i",
      "e",
      "c",
      "t",
      "T"]);return _this14;}_createClass(DateParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "d":return parseNumericPattern(numericPatterns.date, dateString);case "do":return match3.ordinalNumber(dateString, { unit: "date" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(date, value) {var year = date.getFullYear();var isLeapYear3 = isLeapYearIndex(year);var month = date.getMonth();if (isLeapYear3) {return value >= 1 && value <= DAYS_IN_MONTH_LEAP_YEAR[month];} else {return value >= 1 && value <= DAYS_IN_MONTH[month];}} }, { key: "set", value: function set(date, _flags, value) {date.setDate(value);date.setHours(0, 0, 0, 0);return date;} }]);return DateParser;}(Parser);



  // lib/parse/_lib/parsers/DayOfYearParser.mjs
  var DayOfYearParser = /*#__PURE__*/function (_Parser13) {_inherits(DayOfYearParser, _Parser13);function DayOfYearParser() {var _this15;_classCallCheck(this, DayOfYearParser);for (var _len14 = arguments.length, args = new Array(_len14), _key14 = 0; _key14 < _len14; _key14++) {args[_key14] = arguments[_key14];}_this15 = _callSuper(this, DayOfYearParser, [].concat(args));_defineProperty(_assertThisInitialized(_this15), "priority",
      90);_defineProperty(_assertThisInitialized(_this15), "subpriority",
      1);_defineProperty(_assertThisInitialized(_this15), "incompatibleTokens",

























      [
      "Y",
      "R",
      "q",
      "Q",
      "M",
      "L",
      "w",
      "I",
      "d",
      "E",
      "i",
      "e",
      "c",
      "t",
      "T"]);return _this15;}_createClass(DayOfYearParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "D":case "DD":return parseNumericPattern(numericPatterns.dayOfYear, dateString);case "Do":return match3.ordinalNumber(dateString, { unit: "date" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(date, value) {var year = date.getFullYear();var isLeapYear3 = isLeapYearIndex(year);if (isLeapYear3) {return value >= 1 && value <= 366;} else {return value >= 1 && value <= 365;}} }, { key: "set", value: function set(date, _flags, value) {date.setMonth(0, value);date.setHours(0, 0, 0, 0);return date;} }]);return DayOfYearParser;}(Parser);



  // lib/setDay.mjs
  function _setDay(date, day, options) {var _ref30, _ref31, _ref32, _options$weekStartsOn6, _options$locale14, _defaultOptions14$loc;
    var defaultOptions14 = getDefaultOptions();
    var weekStartsOn = (_ref30 = (_ref31 = (_ref32 = (_options$weekStartsOn6 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn6 !== void 0 ? _options$weekStartsOn6 : options === null || options === void 0 || (_options$locale14 = options.locale) === null || _options$locale14 === void 0 || (_options$locale14 = _options$locale14.options) === null || _options$locale14 === void 0 ? void 0 : _options$locale14.weekStartsOn) !== null && _ref32 !== void 0 ? _ref32 : defaultOptions14.weekStartsOn) !== null && _ref31 !== void 0 ? _ref31 : (_defaultOptions14$loc = defaultOptions14.locale) === null || _defaultOptions14$loc === void 0 || (_defaultOptions14$loc = _defaultOptions14$loc.options) === null || _defaultOptions14$loc === void 0 ? void 0 : _defaultOptions14$loc.weekStartsOn) !== null && _ref30 !== void 0 ? _ref30 : 0;
    var _date = _toDate(date);
    var currentDay = _date.getDay();
    var remainder = day % 7;
    var dayIndex = (remainder + 7) % 7;
    var delta = 7 - weekStartsOn;
    var diff = day < 0 || day > 6 ? day - (currentDay + delta) % 7 : (dayIndex + delta) % 7 - (currentDay + delta) % 7;
    return _addDays(_date, diff);
  }

  // lib/parse/_lib/parsers/DayParser.mjs
  var DayParser = /*#__PURE__*/function (_Parser14) {_inherits(DayParser, _Parser14);function DayParser() {var _this16;_classCallCheck(this, DayParser);for (var _len15 = arguments.length, args = new Array(_len15), _key15 = 0; _key15 < _len15; _key15++) {args[_key15] = arguments[_key15];}_this16 = _callSuper(this, DayParser, [].concat(args));_defineProperty(_assertThisInitialized(_this16), "priority",
      90);_defineProperty(_assertThisInitialized(_this16), "incompatibleTokens",
































      ["D", "i", "e", "c", "t", "T"]);return _this16;}_createClass(DayParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "E":case "EE":case "EEE":return match3.day(dateString, { width: "abbreviated", context: "formatting" }) || match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" });case "EEEEE":return match3.day(dateString, { width: "narrow", context: "formatting" });case "EEEEEE":return match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" });case "EEEE":default:return match3.day(dateString, { width: "wide", context: "formatting" }) || match3.day(dateString, { width: "abbreviated", context: "formatting" }) || match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" });}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 6;} }, { key: "set", value: function set(date, _flags, value, options) {date = _setDay(date, value, options);date.setHours(0, 0, 0, 0);return date;} }]);return DayParser;}(Parser);


  // lib/parse/_lib/parsers/LocalDayParser.mjs
  var LocalDayParser = /*#__PURE__*/function (_Parser15) {_inherits(LocalDayParser, _Parser15);function LocalDayParser() {var _this17;_classCallCheck(this, LocalDayParser);for (var _len16 = arguments.length, args = new Array(_len16), _key16 = 0; _key16 < _len16; _key16++) {args[_key16] = arguments[_key16];}_this17 = _callSuper(this, LocalDayParser, [].concat(args));_defineProperty(_assertThisInitialized(_this17), "priority",
      90);_defineProperty(_assertThisInitialized(_this17), "incompatibleTokens",









































      [
      "y",
      "R",
      "u",
      "q",
      "Q",
      "M",
      "L",
      "I",
      "d",
      "D",
      "E",
      "i",
      "c",
      "t",
      "T"]);return _this17;}_createClass(LocalDayParser, [{ key: "parse", value: function parse(dateString, token, match3, options) {var valueCallback = function valueCallback(value) {var wholeWeekDays = Math.floor((value - 1) / 7) * 7;return (value + options.weekStartsOn + 6) % 7 + wholeWeekDays;};switch (token) {case "e":case "ee":return mapValue(parseNDigits(token.length, dateString), valueCallback);case "eo":return mapValue(match3.ordinalNumber(dateString, { unit: "day" }), valueCallback);case "eee":return match3.day(dateString, { width: "abbreviated", context: "formatting" }) || match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" });case "eeeee":return match3.day(dateString, { width: "narrow", context: "formatting" });case "eeeeee":return match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" });case "eeee":default:return match3.day(dateString, { width: "wide", context: "formatting" }) || match3.day(dateString, { width: "abbreviated", context: "formatting" }) || match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" });}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 6;} }, { key: "set", value: function set(date, _flags, value, options) {date = _setDay(date, value, options);date.setHours(0, 0, 0, 0);return date;} }]);return LocalDayParser;}(Parser);



  // lib/parse/_lib/parsers/StandAloneLocalDayParser.mjs
  var StandAloneLocalDayParser = /*#__PURE__*/function (_Parser16) {_inherits(StandAloneLocalDayParser, _Parser16);function StandAloneLocalDayParser() {var _this18;_classCallCheck(this, StandAloneLocalDayParser);for (var _len17 = arguments.length, args = new Array(_len17), _key17 = 0; _key17 < _len17; _key17++) {args[_key17] = arguments[_key17];}_this18 = _callSuper(this, StandAloneLocalDayParser, [].concat(args));_defineProperty(_assertThisInitialized(_this18), "priority",
      90);_defineProperty(_assertThisInitialized(_this18), "incompatibleTokens",









































      [
      "y",
      "R",
      "u",
      "q",
      "Q",
      "M",
      "L",
      "I",
      "d",
      "D",
      "E",
      "i",
      "e",
      "t",
      "T"]);return _this18;}_createClass(StandAloneLocalDayParser, [{ key: "parse", value: function parse(dateString, token, match3, options) {var valueCallback = function valueCallback(value) {var wholeWeekDays = Math.floor((value - 1) / 7) * 7;return (value + options.weekStartsOn + 6) % 7 + wholeWeekDays;};switch (token) {case "c":case "cc":return mapValue(parseNDigits(token.length, dateString), valueCallback);case "co":return mapValue(match3.ordinalNumber(dateString, { unit: "day" }), valueCallback);case "ccc":return match3.day(dateString, { width: "abbreviated", context: "standalone" }) || match3.day(dateString, { width: "short", context: "standalone" }) || match3.day(dateString, { width: "narrow", context: "standalone" });case "ccccc":return match3.day(dateString, { width: "narrow", context: "standalone" });case "cccccc":return match3.day(dateString, { width: "short", context: "standalone" }) || match3.day(dateString, { width: "narrow", context: "standalone" });case "cccc":default:return match3.day(dateString, { width: "wide", context: "standalone" }) || match3.day(dateString, { width: "abbreviated", context: "standalone" }) || match3.day(dateString, { width: "short", context: "standalone" }) || match3.day(dateString, { width: "narrow", context: "standalone" });}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 6;} }, { key: "set", value: function set(date, _flags, value, options) {date = _setDay(date, value, options);date.setHours(0, 0, 0, 0);return date;} }]);return StandAloneLocalDayParser;}(Parser);



  // lib/setISODay.mjs
  function _setISODay(date, day) {
    var _date = _toDate(date);
    var currentDay = _getISODay(_date);
    var diff = day - currentDay;
    return _addDays(_date, diff);
  }

  // lib/parse/_lib/parsers/ISODayParser.mjs
  var ISODayParser = /*#__PURE__*/function (_Parser17) {_inherits(ISODayParser, _Parser17);function ISODayParser() {var _this19;_classCallCheck(this, ISODayParser);for (var _len18 = arguments.length, args = new Array(_len18), _key18 = 0; _key18 < _len18; _key18++) {args[_key18] = arguments[_key18];}_this19 = _callSuper(this, ISODayParser, [].concat(args));_defineProperty(_assertThisInitialized(_this19), "priority",
      90);_defineProperty(_assertThisInitialized(_this19), "incompatibleTokens",






























































      [
      "y",
      "Y",
      "u",
      "q",
      "Q",
      "M",
      "L",
      "w",
      "d",
      "D",
      "E",
      "e",
      "c",
      "t",
      "T"]);return _this19;}_createClass(ISODayParser, [{ key: "parse", value: function parse(dateString, token, match3) {var valueCallback = function valueCallback(value) {if (value === 0) {return 7;}return value;};switch (token) {case "i":case "ii":return parseNDigits(token.length, dateString);case "io":return match3.ordinalNumber(dateString, { unit: "day" });case "iii":return mapValue(match3.day(dateString, { width: "abbreviated", context: "formatting" }) || match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" }), valueCallback);case "iiiii":return mapValue(match3.day(dateString, { width: "narrow", context: "formatting" }), valueCallback);case "iiiiii":return mapValue(match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" }), valueCallback);case "iiii":default:return mapValue(match3.day(dateString, { width: "wide", context: "formatting" }) || match3.day(dateString, { width: "abbreviated", context: "formatting" }) || match3.day(dateString, { width: "short", context: "formatting" }) || match3.day(dateString, { width: "narrow", context: "formatting" }), valueCallback);}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 7;} }, { key: "set", value: function set(date, _flags, value) {date = _setISODay(date, value);date.setHours(0, 0, 0, 0);return date;} }]);return ISODayParser;}(Parser);



  // lib/parse/_lib/parsers/AMPMParser.mjs
  var AMPMParser = /*#__PURE__*/function (_Parser18) {_inherits(AMPMParser, _Parser18);function AMPMParser() {var _this20;_classCallCheck(this, AMPMParser);for (var _len19 = arguments.length, args = new Array(_len19), _key19 = 0; _key19 < _len19; _key19++) {args[_key19] = arguments[_key19];}_this20 = _callSuper(this, AMPMParser, [].concat(args));_defineProperty(_assertThisInitialized(_this20), "priority",
      80);_defineProperty(_assertThisInitialized(_this20), "incompatibleTokens",



































      ["b", "B", "H", "k", "t", "T"]);return _this20;}_createClass(AMPMParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "a":case "aa":case "aaa":return match3.dayPeriod(dateString, { width: "abbreviated", context: "formatting" }) || match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });case "aaaaa":return match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });case "aaaa":default:return match3.dayPeriod(dateString, { width: "wide", context: "formatting" }) || match3.dayPeriod(dateString, { width: "abbreviated", context: "formatting" }) || match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });}} }, { key: "set", value: function set(date, _flags, value) {date.setHours(dayPeriodEnumToHours(value), 0, 0, 0);return date;} }]);return AMPMParser;}(Parser);


  // lib/parse/_lib/parsers/AMPMMidnightParser.mjs
  var AMPMMidnightParser = /*#__PURE__*/function (_Parser19) {_inherits(AMPMMidnightParser, _Parser19);function AMPMMidnightParser() {var _this21;_classCallCheck(this, AMPMMidnightParser);for (var _len20 = arguments.length, args = new Array(_len20), _key20 = 0; _key20 < _len20; _key20++) {args[_key20] = arguments[_key20];}_this21 = _callSuper(this, AMPMMidnightParser, [].concat(args));_defineProperty(_assertThisInitialized(_this21), "priority",
      80);_defineProperty(_assertThisInitialized(_this21), "incompatibleTokens",



































      ["a", "B", "H", "k", "t", "T"]);return _this21;}_createClass(AMPMMidnightParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "b":case "bb":case "bbb":return match3.dayPeriod(dateString, { width: "abbreviated", context: "formatting" }) || match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });case "bbbbb":return match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });case "bbbb":default:return match3.dayPeriod(dateString, { width: "wide", context: "formatting" }) || match3.dayPeriod(dateString, { width: "abbreviated", context: "formatting" }) || match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });}} }, { key: "set", value: function set(date, _flags, value) {date.setHours(dayPeriodEnumToHours(value), 0, 0, 0);return date;} }]);return AMPMMidnightParser;}(Parser);


  // lib/parse/_lib/parsers/DayPeriodParser.mjs
  var DayPeriodParser = /*#__PURE__*/function (_Parser20) {_inherits(DayPeriodParser, _Parser20);function DayPeriodParser() {var _this22;_classCallCheck(this, DayPeriodParser);for (var _len21 = arguments.length, args = new Array(_len21), _key21 = 0; _key21 < _len21; _key21++) {args[_key21] = arguments[_key21];}_this22 = _callSuper(this, DayPeriodParser, [].concat(args));_defineProperty(_assertThisInitialized(_this22), "priority",
      80);_defineProperty(_assertThisInitialized(_this22), "incompatibleTokens",



































      ["a", "b", "t", "T"]);return _this22;}_createClass(DayPeriodParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "B":case "BB":case "BBB":return match3.dayPeriod(dateString, { width: "abbreviated", context: "formatting" }) || match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });case "BBBBB":return match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });case "BBBB":default:return match3.dayPeriod(dateString, { width: "wide", context: "formatting" }) || match3.dayPeriod(dateString, { width: "abbreviated", context: "formatting" }) || match3.dayPeriod(dateString, { width: "narrow", context: "formatting" });}} }, { key: "set", value: function set(date, _flags, value) {date.setHours(dayPeriodEnumToHours(value), 0, 0, 0);return date;} }]);return DayPeriodParser;}(Parser);


  // lib/parse/_lib/parsers/Hour1to12Parser.mjs
  var Hour1to12Parser = /*#__PURE__*/function (_Parser21) {_inherits(Hour1to12Parser, _Parser21);function Hour1to12Parser() {var _this23;_classCallCheck(this, Hour1to12Parser);for (var _len22 = arguments.length, args = new Array(_len22), _key22 = 0; _key22 < _len22; _key22++) {args[_key22] = arguments[_key22];}_this23 = _callSuper(this, Hour1to12Parser, [].concat(args));_defineProperty(_assertThisInitialized(_this23), "priority",
      70);_defineProperty(_assertThisInitialized(_this23), "incompatibleTokens",
























      ["H", "K", "k", "t", "T"]);return _this23;}_createClass(Hour1to12Parser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "h":return parseNumericPattern(numericPatterns.hour12h, dateString);case "ho":return match3.ordinalNumber(dateString, { unit: "hour" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 12;} }, { key: "set", value: function set(date, _flags, value) {var isPM = date.getHours() >= 12;if (isPM && value < 12) {date.setHours(value + 12, 0, 0, 0);} else if (!isPM && value === 12) {date.setHours(0, 0, 0, 0);} else {date.setHours(value, 0, 0, 0);}return date;} }]);return Hour1to12Parser;}(Parser);


  // lib/parse/_lib/parsers/Hour0to23Parser.mjs
  var Hour0to23Parser = /*#__PURE__*/function (_Parser22) {_inherits(Hour0to23Parser, _Parser22);function Hour0to23Parser() {var _this24;_classCallCheck(this, Hour0to23Parser);for (var _len23 = arguments.length, args = new Array(_len23), _key23 = 0; _key23 < _len23; _key23++) {args[_key23] = arguments[_key23];}_this24 = _callSuper(this, Hour0to23Parser, [].concat(args));_defineProperty(_assertThisInitialized(_this24), "priority",
      70);_defineProperty(_assertThisInitialized(_this24), "incompatibleTokens",

















      ["a", "b", "h", "K", "k", "t", "T"]);return _this24;}_createClass(Hour0to23Parser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "H":return parseNumericPattern(numericPatterns.hour23h, dateString);case "Ho":return match3.ordinalNumber(dateString, { unit: "hour" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 23;} }, { key: "set", value: function set(date, _flags, value) {date.setHours(value, 0, 0, 0);return date;} }]);return Hour0to23Parser;}(Parser);


  // lib/parse/_lib/parsers/Hour0To11Parser.mjs
  var Hour0To11Parser = /*#__PURE__*/function (_Parser23) {_inherits(Hour0To11Parser, _Parser23);function Hour0To11Parser() {var _this25;_classCallCheck(this, Hour0To11Parser);for (var _len24 = arguments.length, args = new Array(_len24), _key24 = 0; _key24 < _len24; _key24++) {args[_key24] = arguments[_key24];}_this25 = _callSuper(this, Hour0To11Parser, [].concat(args));_defineProperty(_assertThisInitialized(_this25), "priority",
      70);_defineProperty(_assertThisInitialized(_this25), "incompatibleTokens",






















      ["h", "H", "k", "t", "T"]);return _this25;}_createClass(Hour0To11Parser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "K":return parseNumericPattern(numericPatterns.hour11h, dateString);case "Ko":return match3.ordinalNumber(dateString, { unit: "hour" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 11;} }, { key: "set", value: function set(date, _flags, value) {var isPM = date.getHours() >= 12;if (isPM && value < 12) {date.setHours(value + 12, 0, 0, 0);} else {date.setHours(value, 0, 0, 0);}return date;} }]);return Hour0To11Parser;}(Parser);


  // lib/parse/_lib/parsers/Hour1To24Parser.mjs
  var Hour1To24Parser = /*#__PURE__*/function (_Parser24) {_inherits(Hour1To24Parser, _Parser24);function Hour1To24Parser() {var _this26;_classCallCheck(this, Hour1To24Parser);for (var _len25 = arguments.length, args = new Array(_len25), _key25 = 0; _key25 < _len25; _key25++) {args[_key25] = arguments[_key25];}_this26 = _callSuper(this, Hour1To24Parser, [].concat(args));_defineProperty(_assertThisInitialized(_this26), "priority",
      70);_defineProperty(_assertThisInitialized(_this26), "incompatibleTokens",


















      ["a", "b", "h", "H", "K", "t", "T"]);return _this26;}_createClass(Hour1To24Parser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "k":return parseNumericPattern(numericPatterns.hour24h, dateString);case "ko":return match3.ordinalNumber(dateString, { unit: "hour" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 1 && value <= 24;} }, { key: "set", value: function set(date, _flags, value) {var hours = value <= 24 ? value % 24 : value;date.setHours(hours, 0, 0, 0);return date;} }]);return Hour1To24Parser;}(Parser);


  // lib/parse/_lib/parsers/MinuteParser.mjs
  var MinuteParser = /*#__PURE__*/function (_Parser25) {_inherits(MinuteParser, _Parser25);function MinuteParser() {var _this27;_classCallCheck(this, MinuteParser);for (var _len26 = arguments.length, args = new Array(_len26), _key26 = 0; _key26 < _len26; _key26++) {args[_key26] = arguments[_key26];}_this27 = _callSuper(this, MinuteParser, [].concat(args));_defineProperty(_assertThisInitialized(_this27), "priority",
      60);_defineProperty(_assertThisInitialized(_this27), "incompatibleTokens",

















      ["t", "T"]);return _this27;}_createClass(MinuteParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "m":return parseNumericPattern(numericPatterns.minute, dateString);case "mo":return match3.ordinalNumber(dateString, { unit: "minute" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 59;} }, { key: "set", value: function set(date, _flags, value) {date.setMinutes(value, 0, 0);return date;} }]);return MinuteParser;}(Parser);


  // lib/parse/_lib/parsers/SecondParser.mjs
  var SecondParser = /*#__PURE__*/function (_Parser26) {_inherits(SecondParser, _Parser26);function SecondParser() {var _this28;_classCallCheck(this, SecondParser);for (var _len27 = arguments.length, args = new Array(_len27), _key27 = 0; _key27 < _len27; _key27++) {args[_key27] = arguments[_key27];}_this28 = _callSuper(this, SecondParser, [].concat(args));_defineProperty(_assertThisInitialized(_this28), "priority",
      50);_defineProperty(_assertThisInitialized(_this28), "incompatibleTokens",

















      ["t", "T"]);return _this28;}_createClass(SecondParser, [{ key: "parse", value: function parse(dateString, token, match3) {switch (token) {case "s":return parseNumericPattern(numericPatterns.second, dateString);case "so":return match3.ordinalNumber(dateString, { unit: "second" });default:return parseNDigits(token.length, dateString);}} }, { key: "validate", value: function validate(_date, value) {return value >= 0 && value <= 59;} }, { key: "set", value: function set(date, _flags, value) {date.setSeconds(value, 0);return date;} }]);return SecondParser;}(Parser);


  // lib/parse/_lib/parsers/FractionOfSecondParser.mjs
  var FractionOfSecondParser = /*#__PURE__*/function (_Parser27) {_inherits(FractionOfSecondParser, _Parser27);function FractionOfSecondParser() {var _this29;_classCallCheck(this, FractionOfSecondParser);for (var _len28 = arguments.length, args = new Array(_len28), _key28 = 0; _key28 < _len28; _key28++) {args[_key28] = arguments[_key28];}_this29 = _callSuper(this, FractionOfSecondParser, [].concat(args));_defineProperty(_assertThisInitialized(_this29), "priority",
      30);_defineProperty(_assertThisInitialized(_this29), "incompatibleTokens",








      ["t", "T"]);return _this29;}_createClass(FractionOfSecondParser, [{ key: "parse", value: function parse(dateString, token) {var valueCallback = function valueCallback(value) {return Math.trunc(value * Math.pow(10, -token.length + 3));};return mapValue(parseNDigits(token.length, dateString), valueCallback);} }, { key: "set", value: function set(date, _flags, value) {date.setMilliseconds(value);return date;} }]);return FractionOfSecondParser;}(Parser);


  // lib/parse/_lib/parsers/ISOTimezoneWithZParser.mjs
  var ISOTimezoneWithZParser = /*#__PURE__*/function (_Parser28) {_inherits(ISOTimezoneWithZParser, _Parser28);function ISOTimezoneWithZParser() {var _this30;_classCallCheck(this, ISOTimezoneWithZParser);for (var _len29 = arguments.length, args = new Array(_len29), _key29 = 0; _key29 < _len29; _key29++) {args[_key29] = arguments[_key29];}_this30 = _callSuper(this, ISOTimezoneWithZParser, [].concat(args));_defineProperty(_assertThisInitialized(_this30), "priority",
      10);_defineProperty(_assertThisInitialized(_this30), "incompatibleTokens",




















      ["t", "T", "x"]);return _this30;}_createClass(ISOTimezoneWithZParser, [{ key: "parse", value: function parse(dateString, token) {switch (token) {case "X":return parseTimezonePattern(timezonePatterns.basicOptionalMinutes, dateString);case "XX":return parseTimezonePattern(timezonePatterns.basic, dateString);case "XXXX":return parseTimezonePattern(timezonePatterns.basicOptionalSeconds, dateString);case "XXXXX":return parseTimezonePattern(timezonePatterns.extendedOptionalSeconds, dateString);case "XXX":default:return parseTimezonePattern(timezonePatterns.extended, dateString);}} }, { key: "set", value: function set(date, flags, value) {if (flags.timestampIsSet) return date;return _constructFrom(date, date.getTime() - getTimezoneOffsetInMilliseconds(date) - value);} }]);return ISOTimezoneWithZParser;}(Parser);


  // lib/parse/_lib/parsers/ISOTimezoneParser.mjs
  var ISOTimezoneParser = /*#__PURE__*/function (_Parser29) {_inherits(ISOTimezoneParser, _Parser29);function ISOTimezoneParser() {var _this31;_classCallCheck(this, ISOTimezoneParser);for (var _len30 = arguments.length, args = new Array(_len30), _key30 = 0; _key30 < _len30; _key30++) {args[_key30] = arguments[_key30];}_this31 = _callSuper(this, ISOTimezoneParser, [].concat(args));_defineProperty(_assertThisInitialized(_this31), "priority",
      10);_defineProperty(_assertThisInitialized(_this31), "incompatibleTokens",




















      ["t", "T", "X"]);return _this31;}_createClass(ISOTimezoneParser, [{ key: "parse", value: function parse(dateString, token) {switch (token) {case "x":return parseTimezonePattern(timezonePatterns.basicOptionalMinutes, dateString);case "xx":return parseTimezonePattern(timezonePatterns.basic, dateString);case "xxxx":return parseTimezonePattern(timezonePatterns.basicOptionalSeconds, dateString);case "xxxxx":return parseTimezonePattern(timezonePatterns.extendedOptionalSeconds, dateString);case "xxx":default:return parseTimezonePattern(timezonePatterns.extended, dateString);}} }, { key: "set", value: function set(date, flags, value) {if (flags.timestampIsSet) return date;return _constructFrom(date, date.getTime() - getTimezoneOffsetInMilliseconds(date) - value);} }]);return ISOTimezoneParser;}(Parser);


  // lib/parse/_lib/parsers/TimestampSecondsParser.mjs
  var TimestampSecondsParser = /*#__PURE__*/function (_Parser30) {_inherits(TimestampSecondsParser, _Parser30);function TimestampSecondsParser() {var _this32;_classCallCheck(this, TimestampSecondsParser);for (var _len31 = arguments.length, args = new Array(_len31), _key31 = 0; _key31 < _len31; _key31++) {args[_key31] = arguments[_key31];}_this32 = _callSuper(this, TimestampSecondsParser, [].concat(args));_defineProperty(_assertThisInitialized(_this32), "priority",
      40);_defineProperty(_assertThisInitialized(_this32), "incompatibleTokens",






      "*");return _this32;}_createClass(TimestampSecondsParser, [{ key: "parse", value: function parse(dateString) {return parseAnyDigitsSigned(dateString);} }, { key: "set", value: function set(date, _flags, value) {return [_constructFrom(date, value * 1000), { timestampIsSet: true }];} }]);return TimestampSecondsParser;}(Parser);


  // lib/parse/_lib/parsers/TimestampMillisecondsParser.mjs
  var TimestampMillisecondsParser = /*#__PURE__*/function (_Parser31) {_inherits(TimestampMillisecondsParser, _Parser31);function TimestampMillisecondsParser() {var _this33;_classCallCheck(this, TimestampMillisecondsParser);for (var _len32 = arguments.length, args = new Array(_len32), _key32 = 0; _key32 < _len32; _key32++) {args[_key32] = arguments[_key32];}_this33 = _callSuper(this, TimestampMillisecondsParser, [].concat(args));_defineProperty(_assertThisInitialized(_this33), "priority",
      20);_defineProperty(_assertThisInitialized(_this33), "incompatibleTokens",






      "*");return _this33;}_createClass(TimestampMillisecondsParser, [{ key: "parse", value: function parse(dateString) {return parseAnyDigitsSigned(dateString);} }, { key: "set", value: function set(date, _flags, value) {return [_constructFrom(date, value), { timestampIsSet: true }];} }]);return TimestampMillisecondsParser;}(Parser);


  // lib/parse/_lib/parsers.mjs
  var _parsers = {
    G: new EraParser(),
    y: new YearParser(),
    Y: new LocalWeekYearParser(),
    R: new ISOWeekYearParser(),
    u: new ExtendedYearParser(),
    Q: new QuarterParser(),
    q: new StandAloneQuarterParser(),
    M: new MonthParser(),
    L: new StandAloneMonthParser(),
    w: new LocalWeekParser(),
    I: new ISOWeekParser(),
    d: new DateParser(),
    D: new DayOfYearParser(),
    E: new DayParser(),
    e: new LocalDayParser(),
    c: new StandAloneLocalDayParser(),
    i: new ISODayParser(),
    a: new AMPMParser(),
    b: new AMPMMidnightParser(),
    B: new DayPeriodParser(),
    h: new Hour1to12Parser(),
    H: new Hour0to23Parser(),
    K: new Hour0To11Parser(),
    k: new Hour1To24Parser(),
    m: new MinuteParser(),
    s: new SecondParser(),
    S: new FractionOfSecondParser(),
    X: new ISOTimezoneWithZParser(),
    x: new ISOTimezoneParser(),
    t: new TimestampSecondsParser(),
    T: new TimestampMillisecondsParser()
  };

  // lib/parse.mjs
  function _parse(dateStr, formatStr, referenceDate, options) {var _ref33, _options$locale15, _ref34, _ref35, _ref36, _options$firstWeekCon4, _options$locale16, _defaultOptions14$loc2, _ref37, _ref38, _ref39, _options$weekStartsOn7, _options$locale17, _defaultOptions14$loc3;
    var defaultOptions14 = getDefaultOptions2();
    var locale = (_ref33 = (_options$locale15 = options === null || options === void 0 ? void 0 : options.locale) !== null && _options$locale15 !== void 0 ? _options$locale15 : defaultOptions14.locale) !== null && _ref33 !== void 0 ? _ref33 : enUS;
    var firstWeekContainsDate = (_ref34 = (_ref35 = (_ref36 = (_options$firstWeekCon4 = options === null || options === void 0 ? void 0 : options.firstWeekContainsDate) !== null && _options$firstWeekCon4 !== void 0 ? _options$firstWeekCon4 : options === null || options === void 0 || (_options$locale16 = options.locale) === null || _options$locale16 === void 0 || (_options$locale16 = _options$locale16.options) === null || _options$locale16 === void 0 ? void 0 : _options$locale16.firstWeekContainsDate) !== null && _ref36 !== void 0 ? _ref36 : defaultOptions14.firstWeekContainsDate) !== null && _ref35 !== void 0 ? _ref35 : (_defaultOptions14$loc2 = defaultOptions14.locale) === null || _defaultOptions14$loc2 === void 0 || (_defaultOptions14$loc2 = _defaultOptions14$loc2.options) === null || _defaultOptions14$loc2 === void 0 ? void 0 : _defaultOptions14$loc2.firstWeekContainsDate) !== null && _ref34 !== void 0 ? _ref34 : 1;
    var weekStartsOn = (_ref37 = (_ref38 = (_ref39 = (_options$weekStartsOn7 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn7 !== void 0 ? _options$weekStartsOn7 : options === null || options === void 0 || (_options$locale17 = options.locale) === null || _options$locale17 === void 0 || (_options$locale17 = _options$locale17.options) === null || _options$locale17 === void 0 ? void 0 : _options$locale17.weekStartsOn) !== null && _ref39 !== void 0 ? _ref39 : defaultOptions14.weekStartsOn) !== null && _ref38 !== void 0 ? _ref38 : (_defaultOptions14$loc3 = defaultOptions14.locale) === null || _defaultOptions14$loc3 === void 0 || (_defaultOptions14$loc3 = _defaultOptions14$loc3.options) === null || _defaultOptions14$loc3 === void 0 ? void 0 : _defaultOptions14$loc3.weekStartsOn) !== null && _ref37 !== void 0 ? _ref37 : 0;
    if (formatStr === "") {
      if (dateStr === "") {
        return _toDate(referenceDate);
      } else {
        return _constructFrom(referenceDate, NaN);
      }
    }
    var subFnOptions = {
      firstWeekContainsDate: firstWeekContainsDate,
      weekStartsOn: weekStartsOn,
      locale: locale
    };
    var setters = [new DateToSystemTimezoneSetter()];
    var tokens = formatStr.match(longFormattingTokensRegExp2).map(function (substring) {
      var firstCharacter = substring[0];
      if (firstCharacter in _longFormatters) {
        var longFormatter = _longFormatters[firstCharacter];
        return longFormatter(substring, locale.formatLong);
      }
      return substring;
    }).join("").match(formattingTokensRegExp2);
    var usedTokens = [];var _iterator = _createForOfIteratorHelper(
        tokens),_step;try {var _loop = function _loop() {var token = _step.value;
          if (!(options !== null && options !== void 0 && options.useAdditionalWeekYearTokens) && isProtectedWeekYearToken(token)) {
            warnOrThrowProtectedError(token, formatStr, dateStr);
          }
          if (!(options !== null && options !== void 0 && options.useAdditionalDayOfYearTokens) && isProtectedDayOfYearToken(token)) {
            warnOrThrowProtectedError(token, formatStr, dateStr);
          }
          var firstCharacter = token[0];
          var parser = _parsers[firstCharacter];
          if (parser) {
            var incompatibleTokens = parser.incompatibleTokens;
            if (Array.isArray(incompatibleTokens)) {
              var incompatibleToken = usedTokens.find(function (usedToken) {return incompatibleTokens.includes(usedToken.token) || usedToken.token === firstCharacter;});
              if (incompatibleToken) {
                throw new RangeError("The format string mustn't contain `".concat(incompatibleToken.fullToken, "` and `").concat(token, "` at the same time"));
              }
            } else if (parser.incompatibleTokens === "*" && usedTokens.length > 0) {
              throw new RangeError("The format string mustn't contain `".concat(token, "` and any other token at the same time"));
            }
            usedTokens.push({ token: firstCharacter, fullToken: token });
            var parseResult = parser.run(dateStr, token, locale.match, subFnOptions);
            if (!parseResult) {return { v:
                _constructFrom(referenceDate, NaN) };
            }
            setters.push(parseResult.setter);
            dateStr = parseResult.rest;
          } else {
            if (firstCharacter.match(unescapedLatinCharacterRegExp2)) {
              throw new RangeError("Format string contains an unescaped latin alphabet character `" + firstCharacter + "`");
            }
            if (token === "''") {
              token = "'";
            } else if (firstCharacter === "'") {
              token = cleanEscapedString2(token);
            }
            if (dateStr.indexOf(token) === 0) {
              dateStr = dateStr.slice(token.length);
            } else {return { v:
                _constructFrom(referenceDate, NaN) };
            }
          }
        },_ret;for (_iterator.s(); !(_step = _iterator.n()).done;) {_ret = _loop();if (_ret) return _ret.v;}} catch (err) {_iterator.e(err);} finally {_iterator.f();}
    if (dateStr.length > 0 && notWhitespaceRegExp.test(dateStr)) {
      return _constructFrom(referenceDate, NaN);
    }
    var uniquePrioritySetters = setters.map(function (setter) {return setter.priority;}).sort(function (a, b) {return b - a;}).filter(function (priority, index, array) {return array.indexOf(priority) === index;}).map(function (priority) {return setters.filter(function (setter) {return setter.priority === priority;}).sort(function (a, b) {return b.subPriority - a.subPriority;});}).map(function (setterArray) {return setterArray[0];});
    var date = _toDate(referenceDate);
    if (isNaN(date.getTime())) {
      return _constructFrom(referenceDate, NaN);
    }
    var flags = {};var _iterator2 = _createForOfIteratorHelper(
        uniquePrioritySetters),_step2;try {for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {var setter = _step2.value;
        if (!setter.validate(date, subFnOptions)) {
          return _constructFrom(referenceDate, NaN);
        }
        var result = setter.set(date, flags, subFnOptions);
        if (Array.isArray(result)) {
          date = result[0];
          Object.assign(flags, result[1]);
        } else {
          date = result;
        }
      }} catch (err) {_iterator2.e(err);} finally {_iterator2.f();}
    return _constructFrom(referenceDate, date);
  }
  var cleanEscapedString2 = function cleanEscapedString2(input) {
    return input.match(escapedStringRegExp2)[1].replace(doubleQuoteRegExp2, "'");
  };
  var formattingTokensRegExp2 = /[yYQqMLwIdDecihHKkms]o|(\w)\1*|''|'(''|[^'])+('|$)|./g;
  var longFormattingTokensRegExp2 = /P+p+|P+|p+|''|'(''|[^'])+('|$)|./g;
  var escapedStringRegExp2 = /^'([^]*?)'?$/;
  var doubleQuoteRegExp2 = /''/g;
  var notWhitespaceRegExp = /\S/;
  var unescapedLatinCharacterRegExp2 = /[a-zA-Z]/;

  // lib/isMatch.mjs
  function _isMatch(dateStr, formatStr, options) {
    return _isValid(_parse(dateStr, formatStr, new Date(), options));
  }
  // lib/isMonday.mjs
  function _isMonday(date) {
    return _toDate(date).getDay() === 1;
  }
  // lib/isPast.mjs
  function _isPast(date) {
    return +_toDate(date) < Date.now();
  }
  // lib/startOfHour.mjs
  function _startOfHour(date) {
    var _date = _toDate(date);
    _date.setMinutes(0, 0, 0);
    return _date;
  }

  // lib/isSameHour.mjs
  function _isSameHour(dateLeft, dateRight) {
    var dateLeftStartOfHour = _startOfHour(dateLeft);
    var dateRightStartOfHour = _startOfHour(dateRight);
    return +dateLeftStartOfHour === +dateRightStartOfHour;
  }
  // lib/isSameWeek.mjs
  function _isSameWeek(dateLeft, dateRight, options) {
    var dateLeftStartOfWeek = _startOfWeek(dateLeft, options);
    var dateRightStartOfWeek = _startOfWeek(dateRight, options);
    return +dateLeftStartOfWeek === +dateRightStartOfWeek;
  }

  // lib/isSameISOWeek.mjs
  function _isSameISOWeek(dateLeft, dateRight) {
    return _isSameWeek(dateLeft, dateRight, { weekStartsOn: 1 });
  }
  // lib/isSameISOWeekYear.mjs
  function _isSameISOWeekYear(dateLeft, dateRight) {
    var dateLeftStartOfYear = _startOfISOWeekYear(dateLeft);
    var dateRightStartOfYear = _startOfISOWeekYear(dateRight);
    return +dateLeftStartOfYear === +dateRightStartOfYear;
  }
  // lib/isSameMinute.mjs
  function _isSameMinute(dateLeft, dateRight) {
    var dateLeftStartOfMinute = _startOfMinute(dateLeft);
    var dateRightStartOfMinute = _startOfMinute(dateRight);
    return +dateLeftStartOfMinute === +dateRightStartOfMinute;
  }
  // lib/isSameMonth.mjs
  function _isSameMonth(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    return _dateLeft.getFullYear() === _dateRight.getFullYear() && _dateLeft.getMonth() === _dateRight.getMonth();
  }
  // lib/isSameQuarter.mjs
  function _isSameQuarter(dateLeft, dateRight) {
    var dateLeftStartOfQuarter = _startOfQuarter(dateLeft);
    var dateRightStartOfQuarter = _startOfQuarter(dateRight);
    return +dateLeftStartOfQuarter === +dateRightStartOfQuarter;
  }
  // lib/startOfSecond.mjs
  function _startOfSecond(date) {
    var _date = _toDate(date);
    _date.setMilliseconds(0);
    return _date;
  }

  // lib/isSameSecond.mjs
  function _isSameSecond(dateLeft, dateRight) {
    var dateLeftStartOfSecond = _startOfSecond(dateLeft);
    var dateRightStartOfSecond = _startOfSecond(dateRight);
    return +dateLeftStartOfSecond === +dateRightStartOfSecond;
  }
  // lib/isSameYear.mjs
  function _isSameYear(dateLeft, dateRight) {
    var _dateLeft = _toDate(dateLeft);
    var _dateRight = _toDate(dateRight);
    return _dateLeft.getFullYear() === _dateRight.getFullYear();
  }
  // lib/isThisHour.mjs
  function _isThisHour(date) {
    return _isSameHour(date, _constructNow(date));
  }
  // lib/isThisISOWeek.mjs
  function _isThisISOWeek(date) {
    return _isSameISOWeek(date, _constructNow(date));
  }
  // lib/isThisMinute.mjs
  function _isThisMinute(date) {
    return _isSameMinute(date, _constructNow(date));
  }
  // lib/isThisMonth.mjs
  function _isThisMonth(date) {
    return _isSameMonth(date, _constructNow(date));
  }
  // lib/isThisQuarter.mjs
  function _isThisQuarter(date) {
    return _isSameQuarter(date, _constructNow(date));
  }
  // lib/isThisSecond.mjs
  function _isThisSecond(date) {
    return _isSameSecond(date, _constructNow(date));
  }
  // lib/isThisWeek.mjs
  function _isThisWeek(date, options) {
    return _isSameWeek(date, _constructNow(date), options);
  }
  // lib/isThisYear.mjs
  function _isThisYear(date) {
    return _isSameYear(date, _constructNow(date));
  }
  // lib/isThursday.mjs
  function _isThursday(date) {
    return _toDate(date).getDay() === 4;
  }
  // lib/isToday.mjs
  function _isToday(date) {
    return _isSameDay(date, _constructNow(date));
  }
  // lib/isTomorrow.mjs
  function _isTomorrow(date) {
    return _isSameDay(date, _addDays(_constructNow(date), 1));
  }
  // lib/isTuesday.mjs
  function _isTuesday(date) {
    return _toDate(date).getDay() === 2;
  }
  // lib/isWednesday.mjs
  function _isWednesday(date) {
    return _toDate(date).getDay() === 3;
  }
  // lib/isWithinInterval.mjs
  function _isWithinInterval(date, interval2) {
    var time = +_toDate(date);
    var _sort9 = [
      +_toDate(interval2.start),
      +_toDate(interval2.end)].
      sort(function (a, b) {return a - b;}),_sort10 = _slicedToArray(_sort9, 2),startTime = _sort10[0],endTime = _sort10[1];
    return time >= startTime && time <= endTime;
  }
  // lib/subDays.mjs
  function _subDays(date, amount) {
    return _addDays(date, -amount);
  }

  // lib/isYesterday.mjs
  function _isYesterday(date) {
    return _isSameDay(date, _subDays(_constructNow(date), 1));
  }
  // lib/lastDayOfDecade.mjs
  function _lastDayOfDecade(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var decade = 9 + Math.floor(year / 10) * 10;
    _date.setFullYear(decade + 1, 0, 0);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }
  // lib/lastDayOfWeek.mjs
  function _lastDayOfWeek(date, options) {var _ref40, _ref41, _ref42, _options$weekStartsOn8, _options$locale18, _defaultOptions15$loc;
    var defaultOptions15 = getDefaultOptions();
    var weekStartsOn = (_ref40 = (_ref41 = (_ref42 = (_options$weekStartsOn8 = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn8 !== void 0 ? _options$weekStartsOn8 : options === null || options === void 0 || (_options$locale18 = options.locale) === null || _options$locale18 === void 0 || (_options$locale18 = _options$locale18.options) === null || _options$locale18 === void 0 ? void 0 : _options$locale18.weekStartsOn) !== null && _ref42 !== void 0 ? _ref42 : defaultOptions15.weekStartsOn) !== null && _ref41 !== void 0 ? _ref41 : (_defaultOptions15$loc = defaultOptions15.locale) === null || _defaultOptions15$loc === void 0 || (_defaultOptions15$loc = _defaultOptions15$loc.options) === null || _defaultOptions15$loc === void 0 ? void 0 : _defaultOptions15$loc.weekStartsOn) !== null && _ref40 !== void 0 ? _ref40 : 0;
    var _date = _toDate(date);
    var day = _date.getDay();
    var diff = (day < weekStartsOn ? -7 : 0) + 6 - (day - weekStartsOn);
    _date.setHours(0, 0, 0, 0);
    _date.setDate(_date.getDate() + diff);
    return _date;
  }

  // lib/lastDayOfISOWeek.mjs
  function _lastDayOfISOWeek(date) {
    return _lastDayOfWeek(date, { weekStartsOn: 1 });
  }
  // lib/lastDayOfISOWeekYear.mjs
  function _lastDayOfISOWeekYear(date) {
    var year = _getISOWeekYear(date);
    var fourthOfJanuary = _constructFrom(date, 0);
    fourthOfJanuary.setFullYear(year + 1, 0, 4);
    fourthOfJanuary.setHours(0, 0, 0, 0);
    var _date = _startOfISOWeek(fourthOfJanuary);
    _date.setDate(_date.getDate() - 1);
    return _date;
  }
  // lib/lastDayOfQuarter.mjs
  function _lastDayOfQuarter(date) {
    var _date = _toDate(date);
    var currentMonth = _date.getMonth();
    var month = currentMonth - currentMonth % 3 + 3;
    _date.setMonth(month, 0);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }
  // lib/lastDayOfYear.mjs
  function _lastDayOfYear(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    _date.setFullYear(year + 1, 0, 0);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }
  // lib/lightFormat.mjs
  function _lightFormat(date, formatStr) {
    var _date = _toDate(date);
    if (!_isValid(_date)) {
      throw new RangeError("Invalid time value");
    }
    var tokens = formatStr.match(formattingTokensRegExp3);
    if (!tokens)
    return "";
    var result = tokens.map(function (substring) {
      if (substring === "''") {
        return "'";
      }
      var firstCharacter = substring[0];
      if (firstCharacter === "'") {
        return cleanEscapedString3(substring);
      }
      var formatter = _lightFormatters[firstCharacter];
      if (formatter) {
        return formatter(_date, substring);
      }
      if (firstCharacter.match(unescapedLatinCharacterRegExp3)) {
        throw new RangeError("Format string contains an unescaped latin alphabet character `" + firstCharacter + "`");
      }
      return substring;
    }).join("");
    return result;
  }
  var cleanEscapedString3 = function cleanEscapedString3(input) {
    var matches = input.match(escapedStringRegExp3);
    if (!matches) {
      return input;
    }
    return matches[1].replace(doubleQuoteRegExp3, "'");
  };
  var formattingTokensRegExp3 = /(\w)\1*|''|'(''|[^'])+('|$)|./g;
  var escapedStringRegExp3 = /^'([^]*?)'?$/;
  var doubleQuoteRegExp3 = /''/g;
  var unescapedLatinCharacterRegExp3 = /[a-zA-Z]/;
  // lib/milliseconds.mjs
  function _milliseconds(_ref43)







  {var years = _ref43.years,months2 = _ref43.months,weeks = _ref43.weeks,days2 = _ref43.days,hours = _ref43.hours,minutes = _ref43.minutes,seconds = _ref43.seconds;
    var totalDays = 0;
    if (years)
    totalDays += years * daysInYear;
    if (months2)
    totalDays += months2 * (daysInYear / 12);
    if (weeks)
    totalDays += weeks * 7;
    if (days2)
    totalDays += days2;
    var totalSeconds = totalDays * 24 * 60 * 60;
    if (hours)
    totalSeconds += hours * 60 * 60;
    if (minutes)
    totalSeconds += minutes * 60;
    if (seconds)
    totalSeconds += seconds;
    return Math.trunc(totalSeconds * 1000);
  }
  // lib/millisecondsToHours.mjs
  function _millisecondsToHours(milliseconds2) {
    var hours = milliseconds2 / millisecondsInHour;
    return Math.trunc(hours);
  }
  // lib/millisecondsToMinutes.mjs
  function _millisecondsToMinutes(milliseconds2) {
    var minutes = milliseconds2 / millisecondsInMinute;
    return Math.trunc(minutes);
  }
  // lib/millisecondsToSeconds.mjs
  function _millisecondsToSeconds(milliseconds2) {
    var seconds = milliseconds2 / millisecondsInSecond;
    return Math.trunc(seconds);
  }
  // lib/minutesToHours.mjs
  function _minutesToHours(minutes) {
    var hours = minutes / minutesInHour;
    return Math.trunc(hours);
  }
  // lib/minutesToMilliseconds.mjs
  function _minutesToMilliseconds(minutes) {
    return Math.trunc(minutes * millisecondsInMinute);
  }
  // lib/minutesToSeconds.mjs
  function _minutesToSeconds(minutes) {
    return Math.trunc(minutes * secondsInMinute);
  }
  // lib/monthsToQuarters.mjs
  function _monthsToQuarters(months2) {
    var quarters = months2 / monthsInQuarter;
    return Math.trunc(quarters);
  }
  // lib/monthsToYears.mjs
  function _monthsToYears(months2) {
    var years = months2 / monthsInYear;
    return Math.trunc(years);
  }
  // lib/nextDay.mjs
  function _nextDay(date, day) {
    var delta = day - _getDay(date);
    if (delta <= 0)
    delta += 7;
    return _addDays(date, delta);
  }
  // lib/nextFriday.mjs
  function _nextFriday(date) {
    return _nextDay(date, 5);
  }
  // lib/nextMonday.mjs
  function _nextMonday(date) {
    return _nextDay(date, 1);
  }
  // lib/nextSaturday.mjs
  function _nextSaturday(date) {
    return _nextDay(date, 6);
  }
  // lib/nextSunday.mjs
  function _nextSunday(date) {
    return _nextDay(date, 0);
  }
  // lib/nextThursday.mjs
  function _nextThursday(date) {
    return _nextDay(date, 4);
  }
  // lib/nextTuesday.mjs
  function _nextTuesday(date) {
    return _nextDay(date, 2);
  }
  // lib/nextWednesday.mjs
  function _nextWednesday(date) {
    return _nextDay(date, 3);
  }
  // lib/parseISO.mjs
  function _parseISO(argument, options) {var _options$additionalDi;
    var additionalDigits = (_options$additionalDi = options === null || options === void 0 ? void 0 : options.additionalDigits) !== null && _options$additionalDi !== void 0 ? _options$additionalDi : 2;
    var dateStrings = splitDateString(argument);
    var date;
    if (dateStrings.date) {
      var parseYearResult = parseYear(dateStrings.date, additionalDigits);
      date = parseDate(parseYearResult.restDateString, parseYearResult.year);
    }
    if (!date || isNaN(date.getTime())) {
      return new Date(NaN);
    }
    var timestamp = date.getTime();
    var time = 0;
    var offset;
    if (dateStrings.time) {
      time = parseTime(dateStrings.time);
      if (isNaN(time)) {
        return new Date(NaN);
      }
    }
    if (dateStrings.timezone) {
      offset = parseTimezone(dateStrings.timezone);
      if (isNaN(offset)) {
        return new Date(NaN);
      }
    } else {
      var dirtyDate = new Date(timestamp + time);
      var result = new Date(0);
      result.setFullYear(dirtyDate.getUTCFullYear(), dirtyDate.getUTCMonth(), dirtyDate.getUTCDate());
      result.setHours(dirtyDate.getUTCHours(), dirtyDate.getUTCMinutes(), dirtyDate.getUTCSeconds(), dirtyDate.getUTCMilliseconds());
      return result;
    }
    return new Date(timestamp + time + offset);
  }
  var splitDateString = function splitDateString(dateString) {
    var dateStrings = {};
    var array = dateString.split(patterns.dateTimeDelimiter);
    var timeString;
    if (array.length > 2) {
      return dateStrings;
    }
    if (/:/.test(array[0])) {
      timeString = array[0];
    } else {
      dateStrings.date = array[0];
      timeString = array[1];
      if (patterns.timeZoneDelimiter.test(dateStrings.date)) {
        dateStrings.date = dateString.split(patterns.timeZoneDelimiter)[0];
        timeString = dateString.substr(dateStrings.date.length, dateString.length);
      }
    }
    if (timeString) {
      var token = patterns.timezone.exec(timeString);
      if (token) {
        dateStrings.time = timeString.replace(token[1], "");
        dateStrings.timezone = token[1];
      } else {
        dateStrings.time = timeString;
      }
    }
    return dateStrings;
  };
  var parseYear = function parseYear(dateString, additionalDigits) {
    var regex = new RegExp("^(?:(\\d{4}|[+-]\\d{" + (4 + additionalDigits) + "})|(\\d{2}|[+-]\\d{" + (2 + additionalDigits) + "})$)");
    var captures = dateString.match(regex);
    if (!captures)
    return { year: NaN, restDateString: "" };
    var year = captures[1] ? parseInt(captures[1]) : null;
    var century = captures[2] ? parseInt(captures[2]) : null;
    return {
      year: century === null ? year : century * 100,
      restDateString: dateString.slice((captures[1] || captures[2]).length)
    };
  };
  var parseDate = function parseDate(dateString, year) {
    if (year === null)
    return new Date(NaN);
    var captures = dateString.match(dateRegex);
    if (!captures)
    return new Date(NaN);
    var isWeekDate = !!captures[4];
    var dayOfYear = parseDateUnit(captures[1]);
    var month = parseDateUnit(captures[2]) - 1;
    var day = parseDateUnit(captures[3]);
    var week = parseDateUnit(captures[4]);
    var dayOfWeek = parseDateUnit(captures[5]) - 1;
    if (isWeekDate) {
      if (!validateWeekDate(year, week, dayOfWeek)) {
        return new Date(NaN);
      }
      return dayOfISOWeekYear(year, week, dayOfWeek);
    } else {
      var date = new Date(0);
      if (!validateDate(year, month, day) || !validateDayOfYearDate(year, dayOfYear)) {
        return new Date(NaN);
      }
      date.setUTCFullYear(year, month, Math.max(dayOfYear, day));
      return date;
    }
  };
  var parseDateUnit = function parseDateUnit(value) {
    return value ? parseInt(value) : 1;
  };
  var parseTime = function parseTime(timeString) {
    var captures = timeString.match(timeRegex);
    if (!captures)
    return NaN;
    var hours = parseTimeUnit(captures[1]);
    var minutes = parseTimeUnit(captures[2]);
    var seconds = parseTimeUnit(captures[3]);
    if (!validateTime(hours, minutes, seconds)) {
      return NaN;
    }
    return hours * millisecondsInHour + minutes * millisecondsInMinute + seconds * 1000;
  };
  var parseTimeUnit = function parseTimeUnit(value) {
    return value && parseFloat(value.replace(",", ".")) || 0;
  };
  var parseTimezone = function parseTimezone(timezoneString) {
    if (timezoneString === "Z")
    return 0;
    var captures = timezoneString.match(timezoneRegex);
    if (!captures)
    return 0;
    var sign = captures[1] === "+" ? -1 : 1;
    var hours = parseInt(captures[2]);
    var minutes = captures[3] && parseInt(captures[3]) || 0;
    if (!validateTimezone(hours, minutes)) {
      return NaN;
    }
    return sign * (hours * millisecondsInHour + minutes * millisecondsInMinute);
  };
  var dayOfISOWeekYear = function dayOfISOWeekYear(isoWeekYear, week, day) {
    var date = new Date(0);
    date.setUTCFullYear(isoWeekYear, 0, 4);
    var fourthOfJanuaryDay = date.getUTCDay() || 7;
    var diff = (week - 1) * 7 + day + 1 - fourthOfJanuaryDay;
    date.setUTCDate(date.getUTCDate() + diff);
    return date;
  };
  var isLeapYearIndex2 = function isLeapYearIndex2(year) {
    return year % 400 === 0 || year % 4 === 0 && year % 100 !== 0;
  };
  var validateDate = function validateDate(year, month, date) {
    return month >= 0 && month <= 11 && date >= 1 && date <= (daysInMonths[month] || (isLeapYearIndex2(year) ? 29 : 28));
  };
  var validateDayOfYearDate = function validateDayOfYearDate(year, dayOfYear) {
    return dayOfYear >= 1 && dayOfYear <= (isLeapYearIndex2(year) ? 366 : 365);
  };
  var validateWeekDate = function validateWeekDate(_year, week, day) {
    return week >= 1 && week <= 53 && day >= 0 && day <= 6;
  };
  var validateTime = function validateTime(hours, minutes, seconds) {
    if (hours === 24) {
      return minutes === 0 && seconds === 0;
    }
    return seconds >= 0 && seconds < 60 && minutes >= 0 && minutes < 60 && hours >= 0 && hours < 25;
  };
  var validateTimezone = function validateTimezone(_hours, minutes) {
    return minutes >= 0 && minutes <= 59;
  };
  var patterns = {
    dateTimeDelimiter: /[T ]/,
    timeZoneDelimiter: /[Z ]/i,
    timezone: /([Z+-].*)$/
  };
  var dateRegex = /^-?(?:(\d{3})|(\d{2})(?:-?(\d{2}))?|W(\d{2})(?:-?(\d{1}))?|)$/;
  var timeRegex = /^(\d{2}(?:[.,]\d*)?)(?::?(\d{2}(?:[.,]\d*)?))?(?::?(\d{2}(?:[.,]\d*)?))?$/;
  var timezoneRegex = /^([+-])(\d{2})(?::?(\d{2}))?$/;
  var daysInMonths = [31, null, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  // lib/parseJSON.mjs
  function _parseJSON(dateStr) {
    var parts = dateStr.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{0,7}))?(?:Z|(.)(\d{2}):?(\d{2})?)?/);
    if (parts) {
      return new Date(Date.UTC(+parts[1], +parts[2] - 1, +parts[3], +parts[4] - (+parts[9] || 0) * (parts[8] == "-" ? -1 : 1), +parts[5] - (+parts[10] || 0) * (parts[8] == "-" ? -1 : 1), +parts[6], +((parts[7] || "0") + "00").substring(0, 3)));
    }
    return new Date(NaN);
  }
  // lib/previousDay.mjs
  function _previousDay(date, day) {
    var delta = _getDay(date) - day;
    if (delta <= 0)
    delta += 7;
    return _subDays(date, delta);
  }
  // lib/previousFriday.mjs
  function _previousFriday(date) {
    return _previousDay(date, 5);
  }
  // lib/previousMonday.mjs
  function _previousMonday(date) {
    return _previousDay(date, 1);
  }
  // lib/previousSaturday.mjs
  function _previousSaturday(date) {
    return _previousDay(date, 6);
  }
  // lib/previousSunday.mjs
  function _previousSunday(date) {
    return _previousDay(date, 0);
  }
  // lib/previousThursday.mjs
  function _previousThursday(date) {
    return _previousDay(date, 4);
  }
  // lib/previousTuesday.mjs
  function _previousTuesday(date) {
    return _previousDay(date, 2);
  }
  // lib/previousWednesday.mjs
  function _previousWednesday(date) {
    return _previousDay(date, 3);
  }
  // lib/quartersToMonths.mjs
  function _quartersToMonths(quarters) {
    return Math.trunc(quarters * monthsInQuarter);
  }
  // lib/quartersToYears.mjs
  function _quartersToYears(quarters) {
    var years = quarters / quartersInYear;
    return Math.trunc(years);
  }
  // lib/roundToNearestHours.mjs
  function _roundToNearestHours(date, options) {var _options$nearestTo, _options$roundingMeth2;
    var nearestTo = (_options$nearestTo = options === null || options === void 0 ? void 0 : options.nearestTo) !== null && _options$nearestTo !== void 0 ? _options$nearestTo : 1;
    if (nearestTo < 1 || nearestTo > 12)
    return _constructFrom(date, NaN);
    var _date = _toDate(date);
    var fractionalMinutes = _date.getMinutes() / 60;
    var fractionalSeconds = _date.getSeconds() / 60 / 60;
    var fractionalMilliseconds = _date.getMilliseconds() / 1000 / 60 / 60;
    var hours = _date.getHours() + fractionalMinutes + fractionalSeconds + fractionalMilliseconds;
    var method = (_options$roundingMeth2 = options === null || options === void 0 ? void 0 : options.roundingMethod) !== null && _options$roundingMeth2 !== void 0 ? _options$roundingMeth2 : "round";
    var roundingMethod = getRoundingMethod(method);
    var roundedHours = roundingMethod(hours / nearestTo) * nearestTo;
    var result = _constructFrom(date, _date);
    result.setHours(roundedHours, 0, 0, 0);
    return result;
  }
  // lib/roundToNearestMinutes.mjs
  function _roundToNearestMinutes(date, options) {var _options$nearestTo2, _options$roundingMeth3;
    var nearestTo = (_options$nearestTo2 = options === null || options === void 0 ? void 0 : options.nearestTo) !== null && _options$nearestTo2 !== void 0 ? _options$nearestTo2 : 1;
    if (nearestTo < 1 || nearestTo > 30)
    return _constructFrom(date, NaN);
    var _date = _toDate(date);
    var fractionalSeconds = _date.getSeconds() / 60;
    var fractionalMilliseconds = _date.getMilliseconds() / 1000 / 60;
    var minutes = _date.getMinutes() + fractionalSeconds + fractionalMilliseconds;
    var method = (_options$roundingMeth3 = options === null || options === void 0 ? void 0 : options.roundingMethod) !== null && _options$roundingMeth3 !== void 0 ? _options$roundingMeth3 : "round";
    var roundingMethod = getRoundingMethod(method);
    var roundedMinutes = roundingMethod(minutes / nearestTo) * nearestTo;
    var result = _constructFrom(date, _date);
    result.setMinutes(roundedMinutes, 0, 0);
    return result;
  }
  // lib/secondsToHours.mjs
  function _secondsToHours(seconds) {
    var hours = seconds / secondsInHour;
    return Math.trunc(hours);
  }
  // lib/secondsToMilliseconds.mjs
  function _secondsToMilliseconds(seconds) {
    return seconds * millisecondsInSecond;
  }
  // lib/secondsToMinutes.mjs
  function _secondsToMinutes(seconds) {
    var minutes = seconds / secondsInMinute;
    return Math.trunc(minutes);
  }
  // lib/setMonth.mjs
  function _setMonth(date, month) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var day = _date.getDate();
    var dateWithDesiredMonth = _constructFrom(date, 0);
    dateWithDesiredMonth.setFullYear(year, month, 15);
    dateWithDesiredMonth.setHours(0, 0, 0, 0);
    var daysInMonth = _getDaysInMonth(dateWithDesiredMonth);
    _date.setMonth(month, Math.min(day, daysInMonth));
    return _date;
  }

  // lib/set.mjs
  function _set(date, values) {
    var _date = _toDate(date);
    if (isNaN(+_date)) {
      return _constructFrom(date, NaN);
    }
    if (values.year != null) {
      _date.setFullYear(values.year);
    }
    if (values.month != null) {
      _date = _setMonth(_date, values.month);
    }
    if (values.date != null) {
      _date.setDate(values.date);
    }
    if (values.hours != null) {
      _date.setHours(values.hours);
    }
    if (values.minutes != null) {
      _date.setMinutes(values.minutes);
    }
    if (values.seconds != null) {
      _date.setSeconds(values.seconds);
    }
    if (values.milliseconds != null) {
      _date.setMilliseconds(values.milliseconds);
    }
    return _date;
  }
  // lib/setDate.mjs
  function _setDate(date, dayOfMonth) {
    var _date = _toDate(date);
    _date.setDate(dayOfMonth);
    return _date;
  }
  // lib/setDayOfYear.mjs
  function _setDayOfYear(date, dayOfYear) {
    var _date = _toDate(date);
    _date.setMonth(0);
    _date.setDate(dayOfYear);
    return _date;
  }
  // lib/setDefaultOptions.mjs
  function setDefaultOptions2(options) {
    var result = {};
    var defaultOptions16 = getDefaultOptions();
    for (var property in defaultOptions16) {
      if (Object.prototype.hasOwnProperty.call(defaultOptions16, property)) {
        result[property] = defaultOptions16[property];
      }
    }
    for (var _property in options) {
      if (Object.prototype.hasOwnProperty.call(options, _property)) {
        if (options[_property] === undefined) {
          delete result[_property];
        } else {
          result[_property] = options[_property];
        }
      }
    }
    setDefaultOptions(result);
  }
  // lib/setHours.mjs
  function _setHours(date, hours) {
    var _date = _toDate(date);
    _date.setHours(hours);
    return _date;
  }
  // lib/setMilliseconds.mjs
  function _setMilliseconds(date, milliseconds2) {
    var _date = _toDate(date);
    _date.setMilliseconds(milliseconds2);
    return _date;
  }
  // lib/setMinutes.mjs
  function _setMinutes(date, minutes) {
    var _date = _toDate(date);
    _date.setMinutes(minutes);
    return _date;
  }
  // lib/setQuarter.mjs
  function _setQuarter(date, quarter) {
    var _date = _toDate(date);
    var oldQuarter = Math.trunc(_date.getMonth() / 3) + 1;
    var diff = quarter - oldQuarter;
    return _setMonth(_date, _date.getMonth() + diff * 3);
  }
  // lib/setSeconds.mjs
  function _setSeconds(date, seconds) {
    var _date = _toDate(date);
    _date.setSeconds(seconds);
    return _date;
  }
  // lib/setWeekYear.mjs
  function _setWeekYear(date, weekYear, options) {var _ref44, _ref45, _ref46, _options$firstWeekCon5, _options$locale19, _defaultOptions17$loc;
    var defaultOptions17 = getDefaultOptions();
    var firstWeekContainsDate = (_ref44 = (_ref45 = (_ref46 = (_options$firstWeekCon5 = options === null || options === void 0 ? void 0 : options.firstWeekContainsDate) !== null && _options$firstWeekCon5 !== void 0 ? _options$firstWeekCon5 : options === null || options === void 0 || (_options$locale19 = options.locale) === null || _options$locale19 === void 0 || (_options$locale19 = _options$locale19.options) === null || _options$locale19 === void 0 ? void 0 : _options$locale19.firstWeekContainsDate) !== null && _ref46 !== void 0 ? _ref46 : defaultOptions17.firstWeekContainsDate) !== null && _ref45 !== void 0 ? _ref45 : (_defaultOptions17$loc = defaultOptions17.locale) === null || _defaultOptions17$loc === void 0 || (_defaultOptions17$loc = _defaultOptions17$loc.options) === null || _defaultOptions17$loc === void 0 ? void 0 : _defaultOptions17$loc.firstWeekContainsDate) !== null && _ref44 !== void 0 ? _ref44 : 1;
    var _date = _toDate(date);
    var diff = _differenceInCalendarDays(_date, _startOfWeekYear(_date, options));
    var firstWeek = _constructFrom(date, 0);
    firstWeek.setFullYear(weekYear, 0, firstWeekContainsDate);
    firstWeek.setHours(0, 0, 0, 0);
    _date = _startOfWeekYear(firstWeek, options);
    _date.setDate(_date.getDate() + diff);
    return _date;
  }
  // lib/setYear.mjs
  function _setYear(date, year) {
    var _date = _toDate(date);
    if (isNaN(+_date)) {
      return _constructFrom(date, NaN);
    }
    _date.setFullYear(year);
    return _date;
  }
  // lib/startOfDecade.mjs
  function _startOfDecade(date) {
    var _date = _toDate(date);
    var year = _date.getFullYear();
    var decade = Math.floor(year / 10) * 10;
    _date.setFullYear(decade, 0, 1);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }
  // lib/startOfToday.mjs
  function _startOfToday() {
    return _startOfDay(Date.now());
  }
  // lib/startOfTomorrow.mjs
  function _startOfTomorrow() {
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth();
    var day = now.getDate();
    var date = new Date(0);
    date.setFullYear(year, month, day + 1);
    date.setHours(0, 0, 0, 0);
    return date;
  }
  // lib/startOfYesterday.mjs
  function _startOfYesterday() {
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth();
    var day = now.getDate();
    var date = new Date(0);
    date.setFullYear(year, month, day - 1);
    date.setHours(0, 0, 0, 0);
    return date;
  }
  // lib/subMonths.mjs
  function _subMonths(date, amount) {
    return _addMonths(date, -amount);
  }

  // lib/sub.mjs
  function _sub(date, duration) {
    var _duration$years3 =







      duration.years,years = _duration$years3 === void 0 ? 0 : _duration$years3,_duration$months3 = duration.months,months2 = _duration$months3 === void 0 ? 0 : _duration$months3,_duration$weeks2 = duration.weeks,weeks = _duration$weeks2 === void 0 ? 0 : _duration$weeks2,_duration$days3 = duration.days,days2 = _duration$days3 === void 0 ? 0 : _duration$days3,_duration$hours3 = duration.hours,hours = _duration$hours3 === void 0 ? 0 : _duration$hours3,_duration$minutes3 = duration.minutes,minutes = _duration$minutes3 === void 0 ? 0 : _duration$minutes3,_duration$seconds3 = duration.seconds,seconds = _duration$seconds3 === void 0 ? 0 : _duration$seconds3;
    var dateWithoutMonths = _subMonths(date, months2 + years * 12);
    var dateWithoutDays = _subDays(dateWithoutMonths, days2 + weeks * 7);
    var minutestoSub = minutes + hours * 60;
    var secondstoSub = seconds + minutestoSub * 60;
    var mstoSub = secondstoSub * 1000;
    var finalDate = _constructFrom(date, dateWithoutDays.getTime() - mstoSub);
    return finalDate;
  }
  // lib/subBusinessDays.mjs
  function _subBusinessDays(date, amount) {
    return _addBusinessDays(date, -amount);
  }
  // lib/subHours.mjs
  function _subHours(date, amount) {
    return _addHours(date, -amount);
  }
  // lib/subMilliseconds.mjs
  function _subMilliseconds(date, amount) {
    return _addMilliseconds(date, -amount);
  }
  // lib/subMinutes.mjs
  function _subMinutes(date, amount) {
    return _addMinutes(date, -amount);
  }
  // lib/subQuarters.mjs
  function _subQuarters(date, amount) {
    return _addQuarters(date, -amount);
  }
  // lib/subSeconds.mjs
  function _subSeconds(date, amount) {
    return _addSeconds(date, -amount);
  }
  // lib/subWeeks.mjs
  function _subWeeks(date, amount) {
    return _addWeeks(date, -amount);
  }
  // lib/subYears.mjs
  function _subYears(date, amount) {
    return _addYears(date, -amount);
  }
  // lib/weeksToDays.mjs
  function _weeksToDays(weeks) {
    return Math.trunc(weeks * daysInWeek);
  }
  // lib/yearsToDays.mjs
  function _yearsToDays(years) {
    return Math.trunc(years * daysInYear);
  }
  // lib/yearsToMonths.mjs
  function _yearsToMonths(years) {
    return Math.trunc(years * monthsInYear);
  }
  // lib/yearsToQuarters.mjs
  function _yearsToQuarters(years) {
    return Math.trunc(years * quartersInYear);
  }
  // lib/cdn.js
  window.dateFns = _objectSpread(_objectSpread({},
  window.dateFns),
  exports_lib);


  //# debugId=CCBC78CA46C31FB264756e2164756e21
})();

//# sourceMappingURL=cdn.js.map