export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type AlertSide = "above" | "below" | "left" | "right";
export type AlertAnchorSetting = "auto" | AlertSide;

// Preference order auto has always used: above first, then right, then below,
// then left as the last resort.
export const ALERT_SIDES: readonly AlertSide[] = ["above", "right", "below", "left"];

export interface AlertPlacementRequest {
  anchor: AlertAnchorSetting;
  /** The seed/expanded window the alerts belong to. */
  main: Rect;
  alert: { width: number; height: number };
  /** The crowd-control panel when it is on screen, otherwise null. */
  control: Rect | null;
  workArea: Rect;
  gap: number;
}

export interface AlertPlacement {
  x: number;
  y: number;
  side: AlertSide;
  anchor: AlertAnchorSetting;
}

export function intersects(a: Rect, b: Rect | null | undefined): boolean {
  if (!b) return false;
  return (a.x < b.x + b.width
    && a.x + a.width > b.x
    && a.y < b.y + b.height
    && a.y + a.height > b.y);
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), Math.max(low, high));
}

/** Where the alert sits on a given side before anything is dodged. */
function baseRect(side: AlertSide, request: AlertPlacementRequest): Rect {
  const { main, alert, gap } = request;
  const centredX = main.x + Math.round((main.width - alert.width) / 2);
  const centredY = main.y + Math.round((main.height - alert.height) / 2);
  if (side === "above") {
    return { x: centredX, y: main.y - alert.height - gap, ...alert };
  }
  if (side === "below") {
    return { x: centredX, y: main.y + main.height + gap, ...alert };
  }
  if (side === "left") {
    return { x: main.x - alert.width - gap, y: centredY, ...alert };
  }
  return { x: main.x + main.width + gap, y: centredY, ...alert };
}

// Push the alert further out along the side it is on, so it clears the control
// panel instead of landing on top of it. This generalises what the old code
// did only for a panel sitting above the window.
function clearControl(rect: Rect, side: AlertSide, request: AlertPlacementRequest): Rect {
  const { control, gap } = request;
  if (!intersects(rect, control) || !control) return rect;
  if (side === "above") {
    return { ...rect, y: Math.min(rect.y, control.y - rect.height - gap) };
  }
  if (side === "below") {
    return { ...rect, y: Math.max(rect.y, control.y + control.height + gap) };
  }
  if (side === "left") {
    return { ...rect, x: Math.min(rect.x, control.x - rect.width - gap) };
  }
  return { ...rect, x: Math.max(rect.x, control.x + control.width + gap) };
}

function clampToWorkArea(rect: Rect, workArea: Rect): Rect {
  return {
    ...rect,
    x: clamp(rect.x, workArea.x, workArea.x + workArea.width - rect.width),
    y: clamp(rect.y, workArea.y, workArea.y + workArea.height - rect.height),
  };
}

function resolveSide(side: AlertSide, request: AlertPlacementRequest): Rect {
  return clampToWorkArea(
    clearControl(baseRect(side, request), side, request),
    request.workArea,
  );
}

function fitsOnScreen(rect: Rect, workArea: Rect): boolean {
  return (rect.x >= workArea.x
    && rect.y >= workArea.y
    && rect.x + rect.width <= workArea.x + workArea.width
    && rect.y + rect.height <= workArea.y + workArea.height);
}

/**
 * Choose where the alert stack goes.
 *
 * The control panel is auto-placed on whichever side of the window has room,
 * and it is click-through, so a player cannot drag it out of the way. The
 * alerts therefore have to be the ones that move: `auto` skips any side the
 * panel occupies, and an explicit choice is honoured but pushed clear of the
 * panel rather than drawn over it.
 */
export function placeAlertWindow(request: AlertPlacementRequest): AlertPlacement {
  const { anchor, control, workArea } = request;

  if (anchor !== "auto") {
    const rect = resolveSide(anchor, request);
    return { x: rect.x, y: rect.y, side: anchor, anchor };
  }

  const resolved = ALERT_SIDES.map((side) => ({ side, rect: resolveSide(side, request) }));
  const clear = resolved.find(({ rect }) => (
    fitsOnScreen(rect, workArea) && !intersects(rect, control)
  ));
  // Nothing is both on screen and clear -- prefer staying clear of the panel
  // over staying fully on screen, since an alert drawn over the panel hides
  // the crowd-control timers this window exists to show.
  const fallback = resolved.find(({ rect }) => !intersects(rect, control))
    ?? resolved.find(({ rect }) => fitsOnScreen(rect, workArea))
    ?? resolved[0];
  const chosen = clear ?? fallback;
  return { x: chosen.rect.x, y: chosen.rect.y, side: chosen.side, anchor };
}
