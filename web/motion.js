/* Swarm World viewer: sliding things that move between ticks (wild game, farm animals).
 *
 * Each move keeps its own clock (`at`, when it started), so a later tick never restarts a move that already
 * finished; with one shared clock every animal snapped back a tile and slid again on each tick.
 */
(function () {
  'use strict';

  /** Where a move {fx, fy, tx, ty, at} is drawn at `now`, sliding over `ms`; t runs 0..1. */
  function slide(a, now, ms) {
    const t = Math.max(0, Math.min(1, (now - a.at) / (ms || 1)));
    return { x: a.fx + (a.tx - a.fx) * t, y: a.fy + (a.ty - a.fy) * t, t };
  }

  window.SwarmMotion = { slide };
})();
