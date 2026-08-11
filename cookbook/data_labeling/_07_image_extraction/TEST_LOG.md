# Test Log - _07_image_extraction

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Extracts a typed `Scene` (subject, setting, time_of_day, dominant_colors, notable_objects) from a photo of Krakow's St. Mary's Basilica via `output_schema` on a Gemini agent.

**Result:** Returned `Scene(subject="St. Mary's Basilica viewed through the arches of the Cloth Hall in Kraków", setting='outdoor', time_of_day='dawn_or_dusk', dominant_colors=['blue', 'yellow', 'beige'])` with five notable_objects including "Sukiennice (Cloth Hall) arches" and "Adam Mickiewicz Monument". Run took 6.9s, 1249 total tokens.

---

### ocr_fields.py

**Status:** PASS

**Description:** OCRs a text-heavy image (the Agno intro graphic) into a typed `SignReading` with primary_text, secondary_text list, and color_scheme.

**Result:** Returned `primary_text='What is Agno'`, eight secondary_text entries in reading order (from 'Introduction' through 'Level 5: Agentic Workflows with state and determinism.'), and `color_scheme='Black, White, Red'`. Run took 2.4s, 1246 total tokens.

---

### with_confidence.py

**Status:** PASS

**Description:** Same scene-extraction task with per-field `ConfidentStr` / `ConfidentList` wrappers, using a fjord landscape photo from the gstatic gallery.

**Result:** All five fields populated with `confidence='high'`; subject value 'A deep fjord valley with a river flowing between steep, green mountains', dominant_colors ['blue', 'green', 'grey', 'brown'], notable_objects ['fjord', 'mountains', 'rocky peak', 'valley', 'river']. Nested wrappers deserialized into the Pydantic models correctly. Run took 3.3s, 1332 total tokens.

---
