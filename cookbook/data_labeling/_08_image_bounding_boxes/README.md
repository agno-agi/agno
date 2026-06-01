# Image Bounding Boxes

Detect objects in an image and return their bounding boxes. The model
emits normalized coordinates in `[0, 1]` so the result is resolution-
independent.

## Files

- `basic.py` — detect one labeled object with a bounding box.
- `with_confidence.py` — adds per-box confidence.
- `multi_object.py` — detect multiple objects of multiple classes.

## When to use

- Pre-labeling for an object detection training set (human-in-the-loop
  refinement on top).
- Crop suggestions for product imagery.
- Coarse spatial routing (counting people, vehicles, defects).

For pixel-accurate masks, this primitive isn't the right tool - a
segmentation model is. For "is X in the image" without coordinates, use
[`_06_image_classification/`](../_06_image_classification/) with multilabel.

## Coordinate convention

Coordinates are normalized to the image dimensions:

- `x`, `y` = top-left corner, in `[0, 1]`
- `width`, `height` = box size, in `[0, 1]`

Multiply by the actual image width/height to get pixel coordinates.

## Run

```bash
python cookbook/data_labeling/_08_image_bounding_boxes/basic.py
python cookbook/data_labeling/_08_image_bounding_boxes/with_confidence.py
python cookbook/data_labeling/_08_image_bounding_boxes/multi_object.py
```

Requires `GOOGLE_API_KEY`.
