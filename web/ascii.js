/* Swarm World viewer: ASCII skin, a classic roguelike look.
 *
 * Terrain is characters on a dark background, in the colors of its biome (from the init message's
 * "nature" rows when the world has them); objects are their kind's glyph (the one glyph table, in
 * tiles.js); creatures are "@" in their own color, or their initial when hovered or zoomed in. Glyphs
 * are drawn each frame at the current tile size from cached canvases, so they stay crisp at every zoom.
 * Speech bubbles, night, weather and selection are drawn by the viewer and effects.js on top, as in the
 * other skins.
 */
(function () {
  'use strict';

  const K = window.SwarmTiles;

  // background per biome (m meadow, o oak forest, p pine forest, k marsh, h rocky hills, b beach), and water
  const BG = { m: '#0d140e', o: '#0a120c', p: '#09110f', k: '#0f130b', h: '#121115', b: '#15120c', _: '#0d130e' };
  const WATER_BG = { w: '#0b1724', W: '#07111e', pool: '#0c1716' };
  // [char, color, share] choices per tile and biome; the share is how often the first char is used
  const LAND = {
    g: { _: ['.', '#4f8a4a', '"', '#5a9050', 0.74], k: ['"', '#6c7838', '.', '#5f6c3a', 0.5], o: ['.', '#3f7440', '"', '#4a7e44', 0.8],
         p: ['.', '#3c6e52', '"', '#467a54', 0.8], h: ['.', '#6a7a5e', '"', '#728260', 0.85], b: ['.', '#8a9a62', '"', '#7a9a5a', 0.85] },
    // forest floor: dim, so the trees on it (bright ♣ and ♠ objects) stand out
    f: { _: ['.', '#2c5030', '♣', '#1f4a26', 0.6], p: ['.', '#24483c', '♠', '#1a4436', 0.6] },
    d: { _: [',', '#8a6a48', '.', '#6a5038', 0.6], k: [',', '#7a6a40', '"', '#7a8a40', 0.6] },
    s: { _: ['·', '#c8b080', '.', '#a89060', 0.75] },
    r: { _: ['^', '#8a8490', '.', '#5c5762', 0.5] },
  };
  const ARROWS = '→↘↓↙←↖↑↗';            // flow codes 0..7: east, southeast, south ... northeast (perception.DIRS)
  const FLOW = [[1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]];

  let land = null;                       // { biomes: [rows], flow: [rows] } or null

  const biomeAt = (x, y) => (land && land.biomes && land.biomes[y] && land.biomes[y][x]) || '_';
  const flowAt = (x, y) => {
    const c = land && land.flow && land.flow[y] && land.flow[y][x];
    return c && c !== '.' ? +c : -1;
  };
  function landGlyph(code, x, y) {
    const row = LAND[code] || LAND.g;
    const b = biomeAt(x, y);
    const g = row[b] || row._;
    return K.hash2(x, y, 41) < g[4] ? { char: g[0], color: g[1] } : { char: g[2], color: g[3] };
  }

  /** The background: one pixel per tile (the viewer scales it up without smoothing). */
  function renderTerrain(tiles, width, height, nature) {
    land = nature || null;
    const cv = document.createElement('canvas');
    cv.width = width; cv.height = height;
    const g = cv.getContext('2d');
    for (let y = 0; y < height; y++) {
      const row = tiles[y] || '';
      for (let x = 0; x < width; x++) {
        const c = row[x] || 'g';
        const b = biomeAt(x, y);
        g.fillStyle = c === 'W' ? WATER_BG.W : c === 'w' ? (b === 'k' && flowAt(x, y) < 0 ? WATER_BG.pool : WATER_BG.w) : (BG[b] || BG._);
        g.fillRect(x, y, 1, 1);
      }
    }
    return cv;
  }

  /** Terrain glyphs for the visible tiles, each frame. Tiles with an object show only the object's glyph.
   *  Water shimmers; rivers carry a crest of bright "≈" downstream, with an arrow now and then. */
  function drawGround(ctx, tiles, objAt, x0, y0, x1, y1, ox, oy, ts, now) {
    const opts = { scale: 0.72, outline: false, weight: 500 };
    const wopts = { scale: 0.72, outline: false, weight: 500, alpha: 1 };
    for (let y = y0; y <= y1; y++) {
      const row = tiles[y];
      if (!row) continue;
      const dy = oy + y * ts;
      for (let x = x0; x <= x1; x++) {
        const code = row[x];
        const dx = ox + x * ts;
        if (code === 'w' || code === 'W') {
          const f = code === 'w' ? flowAt(x, y) : -1;
          if (f >= 0) {
            const [fx, fy] = FLOW[f];
            const k = Math.sin((x * fx + y * fy) * 0.9 - now / 380);
            wopts.alpha = 0.45 + 0.55 * Math.max(0, k);
            const arrow = k > 0.93 && K.hash2(x, y, 43) < 0.35;
            K.drawGlyph(ctx, { char: arrow ? ARROWS[f] : '≈', color: arrow ? '#a8dcff' : '#4f9fd8' }, dx, dy, ts, wopts);
          } else {
            const k = Math.sin(now / (code === 'W' ? 1500 : 1100) + K.hash2(x, y, 44) * 6.28);
            wopts.alpha = 0.6 + 0.4 * k;
            const pool = code === 'w' && biomeAt(x, y) === 'k';
            K.drawGlyph(ctx, code === 'W' ? { char: '≈', color: '#2f62a8' } : { char: '~', color: pool ? '#5a9a86' : '#3c8cc0' }, dx, dy, ts, wopts);
          }
          continue;
        }
        if (objAt.has(x + ',' + y)) continue;
        K.drawGlyph(ctx, landGlyph(code, x, y), dx, dy, ts, opts);
      }
    }
  }

  /* --------------------------------------------------------------- objects */
  const FIRE = ['#ffb347', '#ff8a2a', '#ffd27a'];
  const CROP = ['#7fdc6e', '#b8d86a', '#e8c25a'];
  const MOVING = new Set(['honeybee', 'butterfly', 'firefly']);

  function drawObject(ctx, obj, dx, dy, ts, t) {
    let g = K.kindGlyph(obj.kind, obj.id);
    let jx = 0, jy = 0;
    if (obj.kind === 'campfire') g = { char: g.char, color: obj.lit === false ? '#6e5a55' : FIRE[Math.floor(t / 140 + K.hashStr(obj.id)) % FIRE.length] };
    else if (obj.kind === 'crop') g = { char: g.char, color: CROP[Math.max(0, Math.min(2, obj.stage | 0))] };
    if (MOVING.has(obj.kind)) {
      const s = K.hashStr(obj.id) % 100;
      jx = Math.sin(t / 420 + s) * ts * 0.12;
      jy = Math.cos(t / 530 + s * 1.3) * ts * 0.1;
    }
    let alpha = 1;
    if (obj.kind === 'firefly') alpha = 0.55 + 0.45 * Math.sin(t / 380 + K.hashStr(obj.id));
    K.drawGlyph(ctx, g, dx + jx, dy + jy, ts, { scale: 0.86, outline: false, alpha });
  }

  /* ------------------------------------------------------------- creatures */
  /** "@" in the creature's color; its initial when hovered or zoomed in close. opts: { dim, asleep, hover } */
  function drawCreature(ctx, cre, dx, dy, ts, opts) {
    const o = opts || {};
    const name = String(cre.name || '').trim();
    const initial = (o.hover || ts >= 46) && name ? [...name][0].toUpperCase() : '@';
    let color = K.readable(cre.color || '#cfc6b8');
    if (o.dim) color = K.mix(color, '#5c5462', 0.55);
    K.drawGlyph(ctx, { char: initial, color }, dx, dy, ts, { scale: 0.92, outline: true, alpha: o.asleep ? 0.6 : 1, weight: 800 });
  }

  function creatureBadge(cre, px) {
    const dpr = window.devicePixelRatio || 1;
    const cv = document.createElement('canvas');
    cv.width = Math.round(px * dpr); cv.height = Math.round(px * dpr);
    cv.style.width = px + 'px'; cv.style.height = px + 'px';
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = '#0d130e';
    g.fillRect(0, 0, px, px);
    drawCreature(g, cre, 0, 0, px, {});
    return cv;
  }

  window.SwarmASCII = {
    name: 'ascii', credit: 'ASCII skin',
    load: () => Promise.resolve(true), ready: true,
    spriteTopTiles: 1, drawsWater: false,
    renderTerrain, drawGround, drawObject, drawCreature, creatureBadge,
    iconStyle: () => null,
    objectName: K.objectName, terrainName: K.terrainName, hasObject: () => true,
  };
})();
