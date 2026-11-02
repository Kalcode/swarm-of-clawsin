/* Swarm World viewer: roofs.
 *
 * The server lists every finished building with a roof (init and, when one is completed or removed, the tick
 * message): { id, design, x0, y0, x1, y1, door, roof }, a rectangle that includes the walls. This module draws
 * them above the objects and creatures. It decides when, and how opaque; the active skin's drawRoof(ctx, b, x, y,
 * w, h, ts, now) paints the roof itself into the pixel rectangle.
 *
 * Fade rule: a roof is opaque from afar, so a village reads as houses. It fades out (a short ease) as the view
 * zooms in past where interiors read (FADE_FROM to FADE_TO), and always while the followed or selected creature
 * stands on the floor or in the doorway, so you see what it is doing in there. Roofs are decoration only: the
 * creatures read the building as text.
 *
 * Cheap: only buildings on screen are drawn, and nothing allocates per frame (state objects persist per
 * building; skins cache their roof sprites).
 */
(function () {
  'use strict';

  const FADE_FROM = 2.6, FADE_TO = 3.3;   // view zoom: opaque below the first, gone at the second
  const FADE_RATE = 9;                    // per second; about a third of a second to fade
  const NOTCH = 0.55;                     // the door tile's southern part is left open, so the door shows

  let list = [];                          // [{ id, design, x0, y0, x1, y1, door, roof, a }] roofed buildings only
  let byId = new Map();

  const isInt = (n) => Number.isFinite(n);

  /** Replaces the buildings with the server's full list; null or anything else that is not a list means no change. */
  function set(buildings) {
    if (!Array.isArray(buildings)) return;
    const next = [], map = new Map();
    for (const b of buildings) {
      if (!b || !b.roof || !isInt(b.x0) || !isInt(b.y0) || !isInt(b.x1) || !isInt(b.y1) || b.x1 < b.x0 || b.y1 < b.y0) continue;
      const door = Array.isArray(b.door) && isInt(b.door[0]) && isInt(b.door[1]) ? b.door : null;
      const prev = byId.get(b.id);
      const r = { id: b.id, design: String(b.design || ''), x0: b.x0, y0: b.y0, x1: b.x1, y1: b.y1, door, roof: true,
                  a: prev ? prev.a : -1 };
      next.push(r);
      map.set(b.id, r);
    }
    list = next;
    byId = map;
  }

  /** 0 to 1: how opaque this roof wants to be, for the view zoom and the tile (fx, fy) of whoever is followed or selected. */
  function target(b, zoom, fx, fy) {
    const z = Math.max(0, Math.min(1, (FADE_TO - zoom) / (FADE_TO - FADE_FROM)));
    if (fx >= b.x0 + 1 && fx <= b.x1 - 1 && fy >= b.y0 + 1 && fy <= b.y1 - 1) return 0;
    if (b.door && fx === b.door[0] && fy === b.door[1]) return 0;
    return z;
  }

  /** Draws the roofs on screen. V: { ox, oy, ts, x0, y0, x1, y1, dt, zoom, now }; (fx, fy): the tile of the followed or
   *  selected creature, or -1. */
  function draw(ctx, skin, V, fx, fy) {
    if (!list.length || !skin || !skin.drawRoof) return;
    const ts = V.ts, k = 1 - Math.exp(-V.dt * FADE_RATE);
    for (let i = 0; i < list.length; i++) {
      const b = list[i];
      const t = target(b, V.zoom, fx, fy);
      b.a = b.a < 0 ? t : b.a + (t - b.a) * k;
      if (Math.abs(t - b.a) < 0.015) b.a = t;
      if (b.a <= 0) continue;
      if (b.x1 < V.x0 - 1 || b.x0 > V.x1 + 1 || b.y1 < V.y0 - 1 || b.y0 > V.y1 + 1) continue;
      const x = V.ox + b.x0 * ts, y = V.oy + b.y0 * ts, w = (b.x1 - b.x0 + 1) * ts, h = (b.y1 - b.y0 + 1) * ts;
      const was = ctx.globalAlpha;
      ctx.globalAlpha = was * b.a;
      // the roof covers the walls; the doorway stays open, so the door reads as a gap under the eave
      ctx.save();
      ctx.beginPath();
      ctx.rect(x, y, w, h);
      if (b.door) ctx.rect(V.ox + b.door[0] * ts, V.oy + (b.door[1] + 1 - NOTCH) * ts, ts, NOTCH * ts);
      ctx.clip('evenodd');
      skin.drawRoof(ctx, b, x, y, w, h, ts, V.now);
      ctx.restore();
      // the eave: a soft shadow on the ground along the south edge (not across the doorway)
      const e1 = Math.max(1, Math.round(ts * 0.14)), e2 = Math.max(1, Math.round(ts * 0.1));
      const dx = b.door ? V.ox + b.door[0] * ts : -1;
      for (let s = 0; s < 2; s++) {
        ctx.fillStyle = s ? 'rgba(0,0,0,0.12)' : 'rgba(0,0,0,0.26)';
        const yy = y + h + (s ? e1 : 0), hh = s ? e2 : e1;
        if (b.door && dx >= x && dx + ts <= x + w) {
          ctx.fillRect(x, yy, dx - x, hh);
          ctx.fillRect(dx + ts, yy, x + w - dx - ts, hh);
        } else ctx.fillRect(x, yy, w, hh);
      }
      ctx.globalAlpha = was;
    }
  }

  window.SwarmRoofs = {
    set, draw, target, FADE_FROM, FADE_TO,
    get list() { return list; },
    clear() { list = []; byId = new Map(); },
  };
})();
