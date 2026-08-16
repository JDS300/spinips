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

// Base position for a side, with the control panel dodged, but NOT clamped.
// Clamping is deliberately withheld here: a clamped rectangle always fits the
// work area, so testing fit after clamping is a tautology that makes every
// side look viable.
function candidate(side: AlertSide, request: AlertPlacementRequest): Rect {
  return clearControl(baseRect(side, request), side, request);
}

function insideWorkArea(rect: Rect, workArea: Rect): boolean {
  return (rect.x >= workArea.x
    && rect.y >= workArea.y
    && rect.x + rect.width <= workArea.x + workArea.width
    && rect.y + rect.height <= workArea.y + workArea.height);
}

// The seed window is the only way to reach analyze and settings, and the only
// thing a player can drag. An alert card parked on top of it makes the whole
// application unreachable, so overlapping it disqualifies a side outright --
// ahead of honouring a preferred anchor.
function usable(rect: Rect, request: AlertPlacementRequest): boolean {
  return (insideWorkArea(rect, request.workArea)
    && !intersects(rect, request.control)
    && !intersects(rect, request.main));
}

// Mirrors the historic preference: above first, but only while it has at
// least as much room as below; otherwise try the sides before dropping below.
function preferenceOrder(request: AlertPlacementRequest): readonly AlertSide[] {
  const { main, workArea } = request;
  const spaceAbove = main.y - workArea.y;
  const spaceBelow = workArea.y + workArea.height - (main.y + main.height);
  return spaceAbove >= spaceBelow
    ? (["above", "right", "below", "left"] as const)
    : (["right", "below", "left", "above"] as const);
}

/**
 * Choose where the alert stack goes.
 *
 * The control panel is auto-placed on whichever side of the window has room,
 * and it is click-through, so a player cannot drag it out of the way. The
 * alerts therefore have to be the ones that move: they dodge the panel on
 * every side, and they never cover the seed window.
 *
 * Every side yields two candidates -- its natural position, and that position
 * pulled back inside the work area. Near a screen edge the natural one falls
 * off screen while the clamped one can land on the seed, so both are offered
 * and ranked together rather than clamping blindly at the end.
 */
export function placeAlertWindow(request: AlertPlacementRequest): AlertPlacement {
  const { workArea, main } = request;
  const sides = preferenceOrder(request);
  const optionsFor = (side: AlertSide) => {
    const raw = candidate(side, request);
    return [{ side, rect: raw }, { side, rect: clampToWorkArea(raw, workArea) }];
  };
  const preferred = request.anchor === "auto" ? [] : optionsFor(request.anchor);
  const options = [...preferred, ...sides.flatMap(optionsFor)];

  const chosen = options.find(({ rect }) => usable(rect, request))
    // Nothing ideal: staying off the seed matters more than the panel, and
    // both matter more than honouring the requested side.
    ?? options.find(({ rect }) => insideWorkArea(rect, workArea)
      && !intersects(rect, main))
    ?? options.find(({ rect }) => !intersects(rect, main))
    ?? options[0];

  return {
    x: chosen.rect.x,
    y: chosen.rect.y,
    side: chosen.side,
    anchor: request.anchor,
  };
}
