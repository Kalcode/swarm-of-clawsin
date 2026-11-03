/* Swarm World viewer: layers, the surface and the deep below it.
 *
 * The world is one tile map cut into regions, bands of rows that the init message lists: the surface (level 0; rows
 * 0-127 on the default map), a band of solid rock, then the deep (level -1; rows 160-287). The viewer shows one region
 * at a time, keeping world coordinates. This module is its pure logic over plain data (no DOM, no canvas): which
 * region a row is in, where the camera goes when the view switches, keeping the camera in the shown region, which
 * layer follows a climbing creature, how many creatures each region holds, the tick's tile changes, the lights that
 * hole the darkness below, and coordinates counted from the top of the deep.
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

  /** The lights in a region, for the darkness below: [{x, y, r, a, type, kind?}] in tiles (r the radius, a the
   *  strength, 0..1). Lit fires (r 4.6), kinds that glow in their data (r 0.7 + 0.9 x glow: cave mushrooms, crystals,
   *  a crystal lamp), creatures carrying a light (r = their `light`, from the server: a lit torch 4), and the tiles
   *  under an open pit: those whose tile one level up, or a neighbour of it, is "O" (a = clockLight, as bright as the
   *  day or night above). Only lights inside the region; objects and creatures are plain {x, y, ...}. */
  function lightsFor(region, objects, creatures, kindInfo, tiles, regions, clockLight) {
    const out = [];
    if (!region) return out;
    const inside = (y) => y >= region.y0 && y < region.y1;
    for (const o of objects || []) {
      if (!o || !inside(o.y)) continue;
      const info = o.lit ? null : kindInfo && kindInfo(o.kind);
      if (o.lit) out.push({ x: o.x, y: o.y, r: 4.6, a: 1, type: 'fire', kind: o.kind });
      else if (info && info.glow > 0) out.push({ x: o.x, y: o.y, r: 0.7 + 0.9 * info.glow, a: 1, type: 'glow', kind: o.kind });
    }
    for (const c of creatures || []) {
      if (c && c.light > 0 && inside(c.y)) out.push({ x: c.x, y: c.y, r: c.light, a: 1, type: 'carried' });
    }
    const a = Math.max(0, Math.min(1, clockLight));
    for (const t of skylitTiles(region, tiles, regions)) out.push({ x: t.x, y: t.y, r: 1.2, a, type: 'sky' });
    return out;
  }

  /** The tiles of a region open to the sky through an open pit, [{x, y}]: those whose tile one level up, or a
   *  neighbour of it, is "O" (the server's skylight: day or night and rain reach them). The region one level up is
   *  scanned for "O"; the deep's rows lie under its rows. None on the surface (nothing above it). */
  function skylitTiles(region, tiles, regions) {
    const out = [];
    const up = region && (regions || []).find((r) => r.level === region.level + 1);
    if (!up) return out;
    const lit = new Set();
    for (let k = 0; k < up.height; k++) {
      const row = tiles[up.y0 + k];
      if (typeof row !== 'string') continue;
      for (let x = row.indexOf('O'); x >= 0; x = row.indexOf('O', x + 1)) {
        for (let dy = -1; dy <= 1; dy++) {
          const j = k + dy;              // the row offset below; its tile above must lie in the region above
          if (j < 0 || j >= region.height || j >= up.height) continue;
          for (let dx = -1; dx <= 1; dx++) {
            const tx = x + dx;
            if (tx < 0 || tx >= row.length || lit.has(tx + ',' + j)) continue;
            lit.add(tx + ',' + j);
            out.push({ x: tx, y: region.y0 + j });
          }
        }
      }
    }
    return out;
  }

  /** The hole in the dark below round a creature that carries no light, in tiles ({r, a}: radius and strength):
   *  awake, the step it sees (r 1.5); asleep, its mind away, or sleeping, a faint one, so it can still be found. One
   *  that carries a light is lit by lightsFor instead: null. */
  function darkHole(c) {
    if (!c || c.light > 0) return null;
    return c.asleep || c.sleeping ? { r: 0.8, a: 0.28 } : { r: 1.5, a: 0.5 };
  }

  /** A tile's coordinates as people read them: x, then the row counted from the top of its own region, "below" for
   *  a region under the surface ("40, 61 below"); rows in no region as they are. `sep` joins x and y (", "). */
  function placeText(regions, x, y, sep) {
    const r = regionAt(regions, y);
    const s = sep == null ? ', ' : sep;
    if (!r || r.level >= 0) return `${x}${s}${r ? y - r.y0 : y}`;
    return `${x}${s}${y - r.y0} below`;
  }

  window.SwarmLayers = { regionsFrom, regionAt, byName, otherLayer, moveCam, clampCam, followLayer, counts, applyTiles, landFor,
                         lightsFor, skylitTiles, darkHole, placeText };
})();
