// This file is generated automatically by `scripts/build/fp.ts`. Please, don't change it.
import { roundToNearestHours as fn } from "../roundToNearestHours.mjs";
import { convertToFP } from "./_lib/convertToFP.mjs";

export const roundToNearestHoursWithOptions = convertToFP(fn, 2);

// Fallback for modularized imports:
export default roundToNearestHoursWithOptions;
