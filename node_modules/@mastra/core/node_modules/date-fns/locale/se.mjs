import { formatDistance } from "./se/_lib/formatDistance.mjs";
import { formatLong } from "./se/_lib/formatLong.mjs";
import { formatRelative } from "./se/_lib/formatRelative.mjs";
import { localize } from "./se/_lib/localize.mjs";
import { match } from "./se/_lib/match.mjs";

/**
 * @category Locales
 * @summary Northern Sámi locale.
 * @language Northern Sámi
 * @iso-639-2 sme
 * @author Audun Rundberg [@audunru](https://github.com/audunru)
 */
export const se = {
  code: "se",
  formatDistance: formatDistance,
  formatLong: formatLong,
  formatRelative: formatRelative,
  localize: localize,
  match: match,
  options: {
    weekStartsOn: 1 /* Monday */,
    firstWeekContainsDate: 4,
  },
};

// Fallback for modularized imports:
export default se;
