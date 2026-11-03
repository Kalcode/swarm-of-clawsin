/* Swarm World viewer: layers, the surface and the deep below it.
 *
 * The world is one tile map cut into regions, bands of rows that the init message lists: the surface (level 0; rows
 * 0-127 on the default map), a band of solid rock, then the deep (level -1; rows 160-287). The viewer shows one region
 * at a time, keeping world coordinates. This module is its pure logic over plain data (no DOM, no canvas): which
 * region a row is in, where the camera goes when the view switches, keeping the camera in the shown region, which
 * layer follows a climbing creature, how many creatures each region holds, and the tick's tile changes.
 */
(function () {
  'use strict';

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /** The regions in the init message, each with its height; an older server lists none: one surface of the map's
   *  height. */
  function regionsFrom(init) {
    const list = (init && Array.isArray(init.regions) ? init.regions : [])
      .filter((r) => r && typeof r.name === 'string' && r.name && Number.isInteger(r.y0) && Number.isInteger(r.y1) && r.y1 > r.y0)
      .map((r) => ({ name: r.name, level: Number.isInteger(r.level) ? r.level : 0, y0: r.y0, y1: r.y1, height: r.y1 - r.y0,
                     sky: !!r.sky, weather: !!r.weather }));
    if (list.length) return list;
    const height = Math.max(0, (init && init.height) | 0);
    return [{ name: 'surface', level: 0, y0: 0, y1: height, height, sky: true, weather: true }];
  }

  /** The region holding row y, or null (in a band of rock between regions, or off the map). */
  function regionAt(regions, y) {
    for (const r of regions) if (y >= r.y0 && y < r.y1) return r;
    return null;
  }

  function byName(regions, name) {
    for (const r of regions) if (r.name === name) return r;
    return null;
  }

  /** The layer the switch goes to: the next one down, and from the lowest back to the top (surface <-> deep). */
  function otherLayer(regions, name) {
    const order = regions.slice().sort((a, b) => b.level - a.level);
    if (!order.length) return name;
    const i = order.findIndex((r) => r.name === name);
    return order[(i + 1) % order.length].name;
  }

  /** The camera after switching from one region to another: the same x and the same row offset (the deep's rows lie
   *  under the surface's, so a way down and its foot stay in view), kept inside the region it moves to. */
  function moveCam(cam, regions, from, to) {
    const a = byName(regions, from), b = byName(regions, to);
    if (!a || !b) return { x: cam.x, y: cam.y };
    return { x: cam.x, y: clamp(b.y0 + (cam.y - a.y0), b.y0, b.y1) };
  }

  /** The camera kept inside the shown region (its centre may reach the edges, as on a one-region map). */
  function clampCam(cam, region, width) {
    return { x: clamp(cam.x, 0, width), y: region ? clamp(cam.y, region.y0, region.y1) : cam.y };
  }

  /** The layer to show for a followed creature at row y: its region, or the shown layer while it is in none. */
  function followLayer(regions, layer, y) {
    const r = regionAt(regions, y);
    return r ? r.name : layer;
  }

  /** How many creatures ({y}) are in each region: { surface: n, deep: n }. */
  function counts(creatures, regions) {
    const out = {};
    for (const r of regions) out[r.name] = 0;
    for (const c of creatures || []) {
      const r = c && regionAt(regions, c.y);
      if (r) out[r.name]++;
    }
    return out;
  }

  /** The tick's tile changes ([x, y, code], ...) applied to a copy of the rows; dirty: the regions whose terrain
   *  must be drawn again, in the regions' order. Entries off the map or malformed are ignored. */
  function applyTiles(tiles, changes, regions) {
    const rows = new Map();
    const hit = new Set();
    for (const ch of Array.isArray(changes) ? changes : []) {
      if (!Array.isArray(ch)) continue;
      const [x, y, code] = ch;
      if (!Number.isInteger(x) || !Number.isInteger(y) || typeof code !== 'string' || code.length !== 1) continue;
      const row = tiles[y];
      if (typeof row !== 'string' || x < 0 || x >= row.length) continue;
      if (!rows.has(y)) rows.set(y, row.split(''));
      rows.get(y)[x] = code;
      const r = regionAt(regions, y);
      if (r) hit.add(r.name);
    }
    if (!rows.size) return { tiles, dirty: [] };
    const out = tiles.slice();
    for (const [y, chars] of rows) out[y] = chars.join('');
    return { tiles: out, dirty: regions.filter((r) => hit.has(r.name)).map((r) => r.name) };
  }

  /** The init message's land rows (biomes, river flow) to draw the surface with, or null. They cover the surface's
   *  rows only (the deep has none), so they are checked against the surface's height, not the whole map's. A list
   *  with the wrong number of rows, or rows of the wrong width, is left out. */
  function landFor(nature, width, regions) {
    const surface = byName(regions, 'surface');
    if (!surface || !nature || typeof nature !== 'object') return null;
    const h = surface.height;
    const ok = (rows) => Array.isArray(rows) && rows.length === h && rows.every((r) => typeof r === 'string' && r.length === width);
    const land = { biomes: ok(nature.biomes) ? nature.biomes : null, flow: ok(nature.flow) ? nature.flow : null };
    return land.biomes || land.flow ? land : null;
  }

  window.SwarmLayers = { regionsFrom, regionAt, byName, otherLayer, moveCam, clampCam, followLayer, counts, applyTiles, landFor };
})();
