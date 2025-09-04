function ownKeys(e, r) {var t = Object.keys(e);if (Object.getOwnPropertySymbols) {var o = Object.getOwnPropertySymbols(e);r && (o = o.filter(function (r) {return Object.getOwnPropertyDescriptor(e, r).enumerable;})), t.push.apply(t, o);}return t;}function _objectSpread(e) {for (var r = 1; r < arguments.length; r++) {var t = null != arguments[r] ? arguments[r] : {};r % 2 ? ownKeys(Object(t), !0).forEach(function (r) {_defineProperty(e, r, t[r]);}) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) {Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r));});}return e;}function _defineProperty(obj, key, value) {key = _toPropertyKey(key);if (key in obj) {Object.defineProperty(obj, key, { value: value, enumerable: true, configurable: true, writable: true });} else {obj[key] = value;}return obj;}function _toPropertyKey(t) {var i = _toPrimitive(t, "string");return "symbol" == _typeof(i) ? i : String(i);}function _toPrimitive(t, r) {if ("object" != _typeof(t) || !t) return t;var e = t[Symbol.toPrimitive];if (void 0 !== e) {var i = e.call(t, r || "default");if ("object" != _typeof(i)) return i;throw new TypeError("@@toPrimitive must return a primitive value.");}return ("string" === r ? String : Number)(t);}function _typeof(o) {"@babel/helpers - typeof";return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) {return typeof o;} : function (o) {return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o;}, _typeof(o);}(function (_window$dateFns) {var __defProp = Object.defineProperty;
  var __export = function __export(target, all) {
    for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: function set(newValue) {return all[name] = function () {return newValue;};}
    });
  };

  // lib/locale/lv/_lib/formatDistance.mjs
  var buildLocalizeTokenFn = function buildLocalizeTokenFn(schema) {
    return function (count, options) {
      if (count === 1) {
        if (options !== null && options !== void 0 && options.addSuffix) {
          return schema.one[0].replace("{{time}}", schema.one[2]);
        } else {
          return schema.one[0].replace("{{time}}", schema.one[1]);
        }
      } else {
        var rem = count % 10 === 1 && count % 100 !== 11;
        if (options !== null && options !== void 0 && options.addSuffix) {
          return schema.other[0].replace("{{time}}", rem ? schema.other[3] : schema.other[4]).replace("{{count}}", String(count));
        } else {
          return schema.other[0].replace("{{time}}", rem ? schema.other[1] : schema.other[2]).replace("{{count}}", String(count));
        }
      }
    };
  };
  var formatDistanceLocale = {
    lessThanXSeconds: buildLocalizeTokenFn({
      one: ["maz\u0101k par {{time}}", "sekundi", "sekundi"],
      other: [
      "maz\u0101k nek\u0101 {{count}} {{time}}",
      "sekunde",
      "sekundes",
      "sekundes",
      "sekund\u0113m"]

    }),
    xSeconds: buildLocalizeTokenFn({
      one: ["1 {{time}}", "sekunde", "sekundes"],
      other: [
      "{{count}} {{time}}",
      "sekunde",
      "sekundes",
      "sekundes",
      "sekund\u0113m"]

    }),
    halfAMinute: function halfAMinute(_count, options) {
      if (options !== null && options !== void 0 && options.addSuffix) {
        return "pusmin\u016Btes";
      } else {
        return "pusmin\u016Bte";
      }
    },
    lessThanXMinutes: buildLocalizeTokenFn({
      one: ["maz\u0101k par {{time}}", "min\u016Bti", "min\u016Bti"],
      other: [
      "maz\u0101k nek\u0101 {{count}} {{time}}",
      "min\u016Bte",
      "min\u016Btes",
      "min\u016Btes",
      "min\u016Bt\u0113m"]

    }),
    xMinutes: buildLocalizeTokenFn({
      one: ["1 {{time}}", "min\u016Bte", "min\u016Btes"],
      other: ["{{count}} {{time}}", "min\u016Bte", "min\u016Btes", "min\u016Btes", "min\u016Bt\u0113m"]
    }),
    aboutXHours: buildLocalizeTokenFn({
      one: ["apm\u0113ram 1 {{time}}", "stunda", "stundas"],
      other: [
      "apm\u0113ram {{count}} {{time}}",
      "stunda",
      "stundas",
      "stundas",
      "stund\u0101m"]

    }),
    xHours: buildLocalizeTokenFn({
      one: ["1 {{time}}", "stunda", "stundas"],
      other: ["{{count}} {{time}}", "stunda", "stundas", "stundas", "stund\u0101m"]
    }),
    xDays: buildLocalizeTokenFn({
      one: ["1 {{time}}", "diena", "dienas"],
      other: ["{{count}} {{time}}", "diena", "dienas", "dienas", "dien\u0101m"]
    }),
    aboutXWeeks: buildLocalizeTokenFn({
      one: ["apm\u0113ram 1 {{time}}", "ned\u0113\u013Ca", "ned\u0113\u013Cas"],
      other: [
      "apm\u0113ram {{count}} {{time}}",
      "ned\u0113\u013Ca",
      "ned\u0113\u013Cu",
      "ned\u0113\u013Cas",
      "ned\u0113\u013C\u0101m"]

    }),
    xWeeks: buildLocalizeTokenFn({
      one: ["1 {{time}}", "ned\u0113\u013Ca", "ned\u0113\u013Cas"],
      other: [
      "{{count}} {{time}}",
      "ned\u0113\u013Ca",
      "ned\u0113\u013Cu",
      "ned\u0113\u013Cas",
      "ned\u0113\u013C\u0101m"]

    }),
    aboutXMonths: buildLocalizeTokenFn({
      one: ["apm\u0113ram 1 {{time}}", "m\u0113nesis", "m\u0113ne\u0161a"],
      other: [
      "apm\u0113ram {{count}} {{time}}",
      "m\u0113nesis",
      "m\u0113ne\u0161i",
      "m\u0113ne\u0161a",
      "m\u0113ne\u0161iem"]

    }),
    xMonths: buildLocalizeTokenFn({
      one: ["1 {{time}}", "m\u0113nesis", "m\u0113ne\u0161a"],
      other: ["{{count}} {{time}}", "m\u0113nesis", "m\u0113ne\u0161i", "m\u0113ne\u0161a", "m\u0113ne\u0161iem"]
    }),
    aboutXYears: buildLocalizeTokenFn({
      one: ["apm\u0113ram 1 {{time}}", "gads", "gada"],
      other: ["apm\u0113ram {{count}} {{time}}", "gads", "gadi", "gada", "gadiem"]
    }),
    xYears: buildLocalizeTokenFn({
      one: ["1 {{time}}", "gads", "gada"],
      other: ["{{count}} {{time}}", "gads", "gadi", "gada", "gadiem"]
    }),
    overXYears: buildLocalizeTokenFn({
      one: ["ilg\u0101k par 1 {{time}}", "gadu", "gadu"],
      other: ["vair\u0101k nek\u0101 {{count}} {{time}}", "gads", "gadi", "gada", "gadiem"]
    }),
    almostXYears: buildLocalizeTokenFn({
      one: ["gandr\u012Bz 1 {{time}}", "gads", "gada"],
      other: ["vair\u0101k nek\u0101 {{count}} {{time}}", "gads", "gadi", "gada", "gadiem"]
    })
  };
  var formatDistance = function formatDistance(token, count, options) {
    var result = formatDistanceLocale[token](count, options);
    if (options !== null && options !== void 0 && options.addSuffix) {
      if (options.comparison && options.comparison > 0) {
        return "p\u0113c " + result;
      } else {
        return "pirms " + result;
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

  // lib/locale/lv/_lib/formatLong.mjs
  var dateFormats = {
    full: "EEEE, y. 'gada' d. MMMM",
    long: "y. 'gada' d. MMMM",
    medium: "dd.MM.y.",
    short: "dd.MM.y."
  };
  var timeFormats = {
    full: "HH:mm:ss zzzz",
    long: "HH:mm:ss z",
    medium: "HH:mm:ss",
    short: "HH:mm"
  };
  var dateTimeFormats = {
    full: "{{date}} 'plkst.' {{time}}",
    long: "{{date}} 'plkst.' {{time}}",
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

  // lib/toDate.mjs
  function toDate(argument) {
    var argStr = Object.prototype.toString.call(argument);
    if (argument instanceof Date || _typeof(argument) === "object" && argStr === "[object Date]") {
      return new argument.constructor(+argument);
    } else if (typeof argument === "number" || argStr === "[object Number]" || typeof argument === "string" || argStr === "[object String]") {
      return new Date(argument);
    } else {
      return new Date(NaN);
    }
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
  function startOfWeek(date, options) {var _ref, _ref2, _ref3, _options$weekStartsOn, _options$locale, _defaultOptions3$loca;
    var defaultOptions3 = getDefaultOptions();
    var weekStartsOn = (_ref = (_ref2 = (_ref3 = (_options$weekStartsOn = options === null || options === void 0 ? void 0 : options.weekStartsOn) !== null && _options$weekStartsOn !== void 0 ? _options$weekStartsOn : options === null || options === void 0 || (_options$locale = options.locale) === null || _options$locale === void 0 || (_options$locale = _options$locale.options) === null || _options$locale === void 0 ? void 0 : _options$locale.weekStartsOn) !== null && _ref3 !== void 0 ? _ref3 : defaultOptions3.weekStartsOn) !== null && _ref2 !== void 0 ? _ref2 : (_defaultOptions3$loca = defaultOptions3.locale) === null || _defaultOptions3$loca === void 0 || (_defaultOptions3$loca = _defaultOptions3$loca.options) === null || _defaultOptions3$loca === void 0 ? void 0 : _defaultOptions3$loca.weekStartsOn) !== null && _ref !== void 0 ? _ref : 0;
    var _date = toDate(date);
    var day = _date.getDay();
    var diff = (day < weekStartsOn ? 7 : 0) + day - weekStartsOn;
    _date.setDate(_date.getDate() - diff);
    _date.setHours(0, 0, 0, 0);
    return _date;
  }

  // lib/isSameWeek.mjs
  function isSameWeek(dateLeft, dateRight, options) {
    var dateLeftStartOfWeek = startOfWeek(dateLeft, options);
    var dateRightStartOfWeek = startOfWeek(dateRight, options);
    return +dateLeftStartOfWeek === +dateRightStartOfWeek;
  }

  // lib/locale/lv/_lib/formatRelative.mjs
  var weekdays = [
  "sv\u0113tdien\u0101",
  "pirmdien\u0101",
  "otrdien\u0101",
  "tre\u0161dien\u0101",
  "ceturtdien\u0101",
  "piektdien\u0101",
  "sestdien\u0101"];

  var formatRelativeLocale = {
    lastWeek: function lastWeek(date, baseDate, options) {
      if (isSameWeek(date, baseDate, options)) {
        return "eeee 'plkst.' p";
      }
      var weekday = weekdays[date.getDay()];
      return "'Pag\u0101ju\u0161\u0101 " + weekday + " plkst.' p";
    },
    yesterday: "'Vakar plkst.' p",
    today: "'\u0160odien plkst.' p",
    tomorrow: "'R\u012Bt plkst.' p",
    nextWeek: function nextWeek(date, baseDate, options) {
      if (isSameWeek(date, baseDate, options)) {
        return "eeee 'plkst.' p";
      }
      var weekday = weekdays[date.getDay()];
      return "'N\u0101kamaj\u0101 " + weekday + " plkst.' p";
    },
    other: "P"
  };
  var formatRelative = function formatRelative(token, date, baseDate, options) {
    var format = formatRelativeLocale[token];
    if (typeof format === "function") {
      return format(date, baseDate, options);
    }
    return format;
  };

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

  // lib/locale/lv/_lib/localize.mjs
  var eraValues = {
    narrow: ["p.m.\u0113", "m.\u0113"],
    abbreviated: ["p. m. \u0113.", "m. \u0113."],
    wide: ["pirms m\u016Bsu \u0113ras", "m\u016Bsu \u0113r\u0101"]
  };
  var quarterValues = {
    narrow: ["1", "2", "3", "4"],
    abbreviated: ["1. cet.", "2. cet.", "3. cet.", "4. cet."],
    wide: [
    "pirmais ceturksnis",
    "otrais ceturksnis",
    "tre\u0161ais ceturksnis",
    "ceturtais ceturksnis"]

  };
  var formattingQuarterValues = {
    narrow: ["1", "2", "3", "4"],
    abbreviated: ["1. cet.", "2. cet.", "3. cet.", "4. cet."],
    wide: [
    "pirmaj\u0101 ceturksn\u012B",
    "otraj\u0101 ceturksn\u012B",
    "tre\u0161aj\u0101 ceturksn\u012B",
    "ceturtaj\u0101 ceturksn\u012B"]

  };
  var monthValues = {
    narrow: ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
    abbreviated: [
    "janv.",
    "febr.",
    "marts",
    "apr.",
    "maijs",
    "j\u016Bn.",
    "j\u016Bl.",
    "aug.",
    "sept.",
    "okt.",
    "nov.",
    "dec."],

    wide: [
    "janv\u0101ris",
    "febru\u0101ris",
    "marts",
    "apr\u012Blis",
    "maijs",
    "j\u016Bnijs",
    "j\u016Blijs",
    "augusts",
    "septembris",
    "oktobris",
    "novembris",
    "decembris"]

  };
  var formattingMonthValues = {
    narrow: ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
    abbreviated: [
    "janv.",
    "febr.",
    "mart\u0101",
    "apr.",
    "maijs",
    "j\u016Bn.",
    "j\u016Bl.",
    "aug.",
    "sept.",
    "okt.",
    "nov.",
    "dec."],

    wide: [
    "janv\u0101r\u012B",
    "febru\u0101r\u012B",
    "mart\u0101",
    "apr\u012Bl\u012B",
    "maij\u0101",
    "j\u016Bnij\u0101",
    "j\u016Blij\u0101",
    "august\u0101",
    "septembr\u012B",
    "oktobr\u012B",
    "novembr\u012B",
    "decembr\u012B"]

  };
  var dayValues = {
    narrow: ["S", "P", "O", "T", "C", "P", "S"],
    short: ["Sv", "P", "O", "T", "C", "Pk", "S"],
    abbreviated: [
    "sv\u0113td.",
    "pirmd.",
    "otrd.",
    "tre\u0161d.",
    "ceturtd.",
    "piektd.",
    "sestd."],

    wide: [
    "sv\u0113tdiena",
    "pirmdiena",
    "otrdiena",
    "tre\u0161diena",
    "ceturtdiena",
    "piektdiena",
    "sestdiena"]

  };
  var formattingDayValues = {
    narrow: ["S", "P", "O", "T", "C", "P", "S"],
    short: ["Sv", "P", "O", "T", "C", "Pk", "S"],
    abbreviated: [
    "sv\u0113td.",
    "pirmd.",
    "otrd.",
    "tre\u0161d.",
    "ceturtd.",
    "piektd.",
    "sestd."],

    wide: [
    "sv\u0113tdien\u0101",
    "pirmdien\u0101",
    "otrdien\u0101",
    "tre\u0161dien\u0101",
    "ceturtdien\u0101",
    "piektdien\u0101",
    "sestdien\u0101"]

  };
  var dayPeriodValues = {
    narrow: {
      am: "am",
      pm: "pm",
      midnight: "pusn.",
      noon: "pusd.",
      morning: "r\u012Bts",
      afternoon: "diena",
      evening: "vakars",
      night: "nakts"
    },
    abbreviated: {
      am: "am",
      pm: "pm",
      midnight: "pusn.",
      noon: "pusd.",
      morning: "r\u012Bts",
      afternoon: "p\u0113cpusd.",
      evening: "vakars",
      night: "nakts"
    },
    wide: {
      am: "am",
      pm: "pm",
      midnight: "pusnakts",
      noon: "pusdienlaiks",
      morning: "r\u012Bts",
      afternoon: "p\u0113cpusdiena",
      evening: "vakars",
      night: "nakts"
    }
  };
  var formattingDayPeriodValues = {
    narrow: {
      am: "am",
      pm: "pm",
      midnight: "pusn.",
      noon: "pusd.",
      morning: "r\u012Bt\u0101",
      afternoon: "dien\u0101",
      evening: "vakar\u0101",
      night: "nakt\u012B"
    },
    abbreviated: {
      am: "am",
      pm: "pm",
      midnight: "pusn.",
      noon: "pusd.",
      morning: "r\u012Bt\u0101",
      afternoon: "p\u0113cpusd.",
      evening: "vakar\u0101",
      night: "nakt\u012B"
    },
    wide: {
      am: "am",
      pm: "pm",
      midnight: "pusnakt\u012B",
      noon: "pusdienlaik\u0101",
      morning: "r\u012Bt\u0101",
      afternoon: "p\u0113cpusdien\u0101",
      evening: "vakar\u0101",
      night: "nakt\u012B"
    }
  };
  var ordinalNumber = function ordinalNumber(dirtyNumber, _options) {
    var number = Number(dirtyNumber);
    return number + ".";
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
      formattingValues: formattingQuarterValues,
      defaultFormattingWidth: "wide",
      argumentCallback: function argumentCallback(quarter) {return quarter - 1;}
    }),
    month: buildLocalizeFn({
      values: monthValues,
      defaultWidth: "wide",
      formattingValues: formattingMonthValues,
      defaultFormattingWidth: "wide"
    }),
    day: buildLocalizeFn({
      values: dayValues,
      defaultWidth: "wide",
      formattingValues: formattingDayValues,
      defaultFormattingWidth: "wide"
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

  // lib/locale/lv/_lib/match.mjs
  var matchOrdinalNumberPattern = /^(\d+)\./i;
  var parseOrdinalNumberPattern = /\d+/i;
  var matchEraPatterns = {
    narrow: /^(p\.m\.ē|m\.ē)/i,
    abbreviated: /^(p\. m\. ē\.|m\. ē\.)/i,
    wide: /^(pirms mūsu ēras|mūsu ērā)/i
  };
  var parseEraPatterns = {
    any: [/^p/i, /^m/i]
  };
  var matchQuarterPatterns = {
    narrow: /^[1234]/i,
    abbreviated: /^[1234](\. cet\.)/i,
    wide: /^(pirma(is|jā)|otra(is|jā)|treša(is|jā)|ceturta(is|jā)) ceturksn(is|ī)/i
  };
  var parseQuarterPatterns = {
    narrow: [/^1/i, /^2/i, /^3/i, /^4/i],
    abbreviated: [/^1/i, /^2/i, /^3/i, /^4/i],
    wide: [/^p/i, /^o/i, /^t/i, /^c/i]
  };
  var matchMonthPatterns = {
    narrow: /^[jfmasond]/i,
    abbreviated: /^(janv\.|febr\.|marts|apr\.|maijs|jūn\.|jūl\.|aug\.|sept\.|okt\.|nov\.|dec\.)/i,
    wide: /^(janvār(is|ī)|februār(is|ī)|mart[sā]|aprīl(is|ī)|maij[sā]|jūnij[sā]|jūlij[sā]|august[sā]|septembr(is|ī)|oktobr(is|ī)|novembr(is|ī)|decembr(is|ī))/i
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
    /^mai/i,
    /^jūn/i,
    /^jūl/i,
    /^au/i,
    /^s/i,
    /^o/i,
    /^n/i,
    /^d/i]

  };
  var matchDayPatterns = {
    narrow: /^[spotc]/i,
    short: /^(sv|pi|o|t|c|pk|s)/i,
    abbreviated: /^(svētd\.|pirmd\.|otrd.\|trešd\.|ceturtd\.|piektd\.|sestd\.)/i,
    wide: /^(svētdien(a|ā)|pirmdien(a|ā)|otrdien(a|ā)|trešdien(a|ā)|ceturtdien(a|ā)|piektdien(a|ā)|sestdien(a|ā))/i
  };
  var parseDayPatterns = {
    narrow: [/^s/i, /^p/i, /^o/i, /^t/i, /^c/i, /^p/i, /^s/i],
    any: [/^sv/i, /^pi/i, /^o/i, /^t/i, /^c/i, /^p/i, /^se/i]
  };
  var matchDayPeriodPatterns = {
    narrow: /^(am|pm|pusn\.|pusd\.|rīt(s|ā)|dien(a|ā)|vakar(s|ā)|nakt(s|ī))/,
    abbreviated: /^(am|pm|pusn\.|pusd\.|rīt(s|ā)|pēcpusd\.|vakar(s|ā)|nakt(s|ī))/,
    wide: /^(am|pm|pusnakt(s|ī)|pusdienlaik(s|ā)|rīt(s|ā)|pēcpusdien(a|ā)|vakar(s|ā)|nakt(s|ī))/i
  };
  var parseDayPeriodPatterns = {
    any: {
      am: /^am/i,
      pm: /^pm/i,
      midnight: /^pusn/i,
      noon: /^pusd/i,
      morning: /^r/i,
      afternoon: /^(d|pēc)/i,
      evening: /^v/i,
      night: /^n/i
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
      defaultParseWidth: "wide",
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
      defaultMatchWidth: "wide",
      parsePatterns: parseDayPeriodPatterns,
      defaultParseWidth: "any"
    })
  };

  // lib/locale/lv.mjs
  var lv = {
    code: "lv",
    formatDistance: formatDistance,
    formatLong: formatLong,
    formatRelative: formatRelative,
    localize: localize,
    match: match,
    options: {
      weekStartsOn: 1,
      firstWeekContainsDate: 4
    }
  };

  // lib/locale/lv/cdn.js
  window.dateFns = _objectSpread(_objectSpread({},
  window.dateFns), {}, {
    locale: _objectSpread(_objectSpread({}, (_window$dateFns =
    window.dateFns) === null || _window$dateFns === void 0 ? void 0 : _window$dateFns.locale), {}, {
      lv: lv }) });



  //# debugId=E2216A899EA74EDA64756e2164756e21
})();

//# sourceMappingURL=cdn.js.map