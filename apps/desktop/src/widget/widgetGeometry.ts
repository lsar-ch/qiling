export const BUBBLE_TOP_MARGIN = 8;
export const BUBBLE_MAX_HEIGHT = 378;

/** The bubble moves down by the same amount that a bottom-anchored window grows. */
export function widgetHeightForBubble(baseHeight: number, viewportHeight: number, bubbleTop: number | null): number {
  return bubbleTop === null
    ? baseHeight
    : Math.max(baseHeight, Math.ceil(viewportHeight - bubbleTop + BUBBLE_TOP_MARGIN));
}

export function bubbleHeightForWindow(windowHeight: number, distanceFromBottom: number): number {
  return Math.max(35, Math.min(BUBBLE_MAX_HEIGHT, Math.floor(windowHeight - distanceFromBottom - BUBBLE_TOP_MARGIN)));
}
