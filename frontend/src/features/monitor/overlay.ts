/**
 * Pure helper for mapping normalised detection boxes to displayed pixel
 * coordinates, accounting for `object-fit: contain` letterboxing and
 * devicePixelRatio.
 *
 * Exported separately so it can be unit-tested without React/DOM.
 */

export interface DisplayRect {
  /** Offset of the visible video area within the element. */
  offsetX: number;
  offsetY: number;
  /** Size of the visible video area on screen. */
  displayWidth: number;
  displayHeight: number;
}

/**
 * Compute the displayed rectangle of a video with `object-fit: contain`
 * inside an element of `elementWidth × elementHeight`.
 */
export function computeContainRect(
  videoWidth: number,
  videoHeight: number,
  elementWidth: number,
  elementHeight: number,
): DisplayRect {
  if (
    videoWidth <= 0 ||
    videoHeight <= 0 ||
    elementWidth <= 0 ||
    elementHeight <= 0
  ) {
    return { offsetX: 0, offsetY: 0, displayWidth: 0, displayHeight: 0 };
  }
  const videoAspect = videoWidth / videoHeight;
  const elementAspect = elementWidth / elementHeight;

  let displayWidth: number;
  let displayHeight: number;

  if (videoAspect > elementAspect) {
    // Video is wider: pillarboxed (black bars top/bottom)
    displayWidth = elementWidth;
    displayHeight = elementWidth / videoAspect;
  } else {
    // Video is taller: letterboxed (black bars left/right)
    displayHeight = elementHeight;
    displayWidth = elementHeight * videoAspect;
  }

  const offsetX = (elementWidth - displayWidth) / 2;
  const offsetY = (elementHeight - displayHeight) / 2;

  return { offsetX, offsetY, displayWidth, displayHeight };
}

export interface PixelBox {
  x: number;
  y: number;
  w: number;
  h: number;
  conf: number;
}

/**
 * Convert normalised boxes [x1, y1, x2, y2, conf] (0..1) to pixel
 * coordinates on a canvas that covers the video element.
 *
 * `dpr` is `devicePixelRatio` — the canvas is sized in CSS pixels but
 * drawn in physical pixels.
 */
export function mapBoxes(
  boxes: [number, number, number, number, number][],
  display: DisplayRect,
  dpr: number,
): PixelBox[] {
  return boxes.map(([x1, y1, x2, y2, conf]) => ({
    x: (display.offsetX + x1 * display.displayWidth) * dpr,
    y: (display.offsetY + y1 * display.displayHeight) * dpr,
    w: (x2 - x1) * display.displayWidth * dpr,
    h: (y2 - y1) * display.displayHeight * dpr,
    conf,
  }));
}
