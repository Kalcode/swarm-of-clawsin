/* Swarm World viewer: LimeZu skin (default when web/assets/limezu/ is present).
 *
 * Art: LimeZu (limezu.itch.io): Modern Exteriors, Modern Interiors, Modern
 * Farm and Serene Village, 16x16 versions. The packs are licensed to the user
 * and must not be redistributed, so web/assets/limezu/ is gitignored; when it
 * is missing the viewer falls back to the Kenney skin in tiles.js.
 *
 * Everything is driven by web/assets/limezu/manifest.json: kind/item -> sheet
 * + rect (+ frames). New kinds only need a manifest entry. Kinds without one
 * are drawn as their roguelike glyph (tiles.js) so they still show up. The
 * manifest may also hold pieces of the Modern User Interface pack ("ui"),
 * which dress the viewer's chrome while this skin is on.
 */
(function () {
  'use strict';

  const BASE = 'assets/limezu/';
  // The public page loads its scripts as name.js?v=<version>; the files under assets/ then carry the same ?v=, so the
  // edge keeps them for good. The private viewer's script URLs have no version, and neither do its assets.
  const VQ = (() => {
    const m = /\?(v=[\w-]+)$/.exec((document.currentScript && document.currentScript.getAttribute('src')) || '');
    return m ? '?' + m[1] : '';
  })();
  const K = window.SwarmTiles;           // Kenney skin, used for unknown kinds and helpers
  const TILE = 16;

  let M = null;                          // manifest
  const img = {};                        // sheet name -> HTMLImageElement
  let ready = false;

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error('missing ' + src));
      i.src = src;
    });
  }

  async function load() {
    try {
      const r = await fetch(BASE + 'manifest.json' + VQ, { cache: 'no-cache' });
      if (!r.ok) return false;
      M = await r.json();
      const jobs = [];
      for (const [name, file] of Object.entries(M.sheets)) jobs.push(loadImage(BASE + file + VQ).then((i) => { img[name] = i; }));
      for (const layer of M.characters.layers) {
        jobs.push(loadImage(BASE + M.characters[layer].src + VQ).then((i) => { img['ch_' + layer] = i; }));
      }
      for (const kind of animalKinds()) {
        for (const file of M.animals[kind].sheets) jobs.push(loadImage(BASE + file + VQ).then((i) => { img[file] = i; }));
      }
      await Promise.all(jobs);
      buildUI();
      ready = true;
      return true;
    } catch (err) {
      console.info('[limezu] skin unavailable, using Kenney art:', err.message);
      return false;
    }
  }

  const hash = (s) => K.hashStr(s);
  // every manifest animal with sheets (chicken, sheep, cow, and the wild game)
  const animalKinds = () => Object.keys(M.animals || {}).filter((k) => M.animals[k] && Array.isArray(M.animals[k].sheets));
  const pickVariant = (spec, id) => spec.variants[hash(id) % spec.variants.length];

  /* --------------------------------------------------------------- terrain */
  const isWater = (c) => c === 'w' || c === 'W';       // the surface's water, with beaches (cave water has none)
  const isGrassy = (c) => c === 'g' || c === 'f';
  // cave water is the pack's water, darkened (a build's own "tint" for it wins)
  const TINT = { u: 'rgba(2,18,26,0.58)' };

  /** A tile the build has no flat for (the deep's rock and floor, dug land): its ground in the Kenney palette, with
   *  a speckle of the same art's stone or earth. The user's packs may add flats for these codes in the build. */
  function fallbackTile(g, code, x, y, x0, hx) {
    const t = K.TERRAIN[code];
    const px = (x - x0) * TILE, py = y * TILE;
    g.fillStyle = t.base[Math.floor(K.hash2(x - hx, y, 3) * t.base.length)];
    g.fillRect(px, py, TILE, TILE);
    const n = Math.round((t.density || 0) * 7);
    for (let i = 0; i < n; i++) {
      g.fillStyle = i % 3 === 2 ? 'rgba(0,0,0,0.35)' : t.tint;
      g.fillRect(px + 1 + Math.floor(K.hash2(x - hx, y, 10 + i) * 13), py + 1 + Math.floor(K.hash2(x - hx, y, 20 + i) * 13), 2, 1 + (i & 1));
    }
  }

  /** Draws one tile of a 3x3 + inner-corner autotile set, quarter by quarter
   *  (8x8 each), so thin strips and single-tile peninsulas get edges on every
   *  side. o = [n, e, s, w, ne, se, sw, nw]: true where the neighbour is the
   *  "other" terrain. Quarters with nothing to show are skipped unless `fill`. */
  function drawAutotile(g, sheet, set, inner, o, x, y, fill, x0) {
    const [n, e, s, w, ne, se, sw, nw] = o;
    if (!fill && !(n || e || s || w || ne || se || sw || nw)) return false;
    const H = TILE / 2;
    for (let qy = 0; qy < 2; qy++) {
      for (let qx = 0; qx < 2; qx++) {
        const V = qy ? s : n, Hz = qx ? e : w, D = qy ? (qx ? se : sw) : (qx ? ne : nw);
        let sx, sy;
        if (V && Hz) { sx = set[0] + (qx ? 2 : 0) * TILE; sy = set[1] + (qy ? 2 : 0) * TILE; }
        else if (V) { sx = set[0] + TILE; sy = set[1] + (qy ? 2 : 0) * TILE; }
        else if (Hz) { sx = set[0] + (qx ? 2 : 0) * TILE; sy = set[1] + TILE; }
        else if (D) { sx = inner[0] + (1 - qx) * TILE; sy = inner[1] + (1 - qy) * TILE; }
        else if (fill) { sx = set[0] + TILE; sy = set[1] + TILE; }
        else continue;
        g.drawImage(sheet, sx + qx * H, sy + qy * H, H, H, (x - x0) * TILE + qx * H, y * TILE + qy * H, H, H);
      }
    }
    return true;
  }

  // biomes (init's nature rows) tint the land a little: an olive marsh, a cool dark pine forest, grey hills
  const BIOME_TINT = { k: 'rgba(96,88,20,0.22)', p: 'rgba(0,26,40,0.22)', h: 'rgba(64,52,64,0.14)', b: 'rgba(120,96,40,0.06)' };

  /** Columns span.x0..x1-1 of the map (all by default). Tile looks are hashed on x - span.hx; neighbours (beaches,
   *  grass edges, wall edges) are read from the full rows, so a chunk's edge tiles look as they do in the whole map.
   *  The smooth tints are painted from a few columns of padding either side, so chunks blend into each other. */
  function renderTerrain(tiles, width, height, land, span) {
    const { x0, x1, hx } = span || { x0: 0, x1: width, hx: 0 };
    const cv = document.createElement('canvas');
    cv.width = (x1 - x0) * TILE;
    cv.height = height * TILE;
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    const T = M.terrain;
    const sheet = img[T.sheet];
    const at = (x, y) => {
      const cx = Math.max(0, Math.min(width - 1, x)), cy = Math.max(0, Math.min(height - 1, y));
      return (tiles[cy] && tiles[cy][cx]) || 'g';
    };
    const blit = (rect, x, y) => g.drawImage(sheet, rect[0], rect[1], TILE, TILE, (x - x0) * TILE, y * TILE, TILE, TILE);
    const near = (x, y, pred) => [
      pred(at(x, y - 1)), pred(at(x + 1, y)), pred(at(x, y + 1)), pred(at(x - 1, y)),
      pred(at(x + 1, y - 1)), pred(at(x + 1, y + 1)), pred(at(x - 1, y + 1)), pred(at(x - 1, y - 1)),
    ];
    const shore = T.autotiles.shore, hole = T.autotiles.grassHole;
    // land touching water is drawn as beach; everything else keeps its own ground (worked out one column beyond the
    // span, which the grass edges look at)
    const bx0 = Math.max(0, x0 - 1), bx1 = Math.min(width, x1 + 1);
    const beach = new Uint8Array(width * height);
    for (let y = 0; y < height; y++) {
      for (let x = bx0; x < bx1; x++) {
        if (!isWater(at(x, y)) && near(x, y, isWater).some(Boolean)) beach[y * width + x] = 1;
      }
    }
    const isBeach = (x, y) => beach[Math.max(0, Math.min(height - 1, y)) * width + Math.max(0, Math.min(width - 1, x))] === 1;
    const lush = (x, y) => isGrassy(at(x, y)) && !isBeach(x, y);
    const flatHash = (x, y) => hash((x - hx) + ',' + y);

    for (let y = 0; y < height; y++) {
      for (let x = x0; x < x1; x++) {
        const c = at(x, y);
        const flats = T.flats[c] || (c === 'u' && T.flats.w);
        if (flats) blit(flats[flatHash(x, y) % flats.length], x, y);
        else if (K.TERRAIN[c]) fallbackTile(g, c, x, y, x0, hx);
        else blit(T.flats.g[flatHash(x, y) % T.flats.g.length], x, y);
        if (!isWater(c)) {
          // land touching water becomes a little beach with a foam edge
          if (isBeach(x, y)) drawAutotile(g, sheet, shore.set, shore.inner, near(x, y, isWater), x, y, true, x0);
        }
      }
    }
    // Deep water and forest floor are darker versions of water and grass. The
    // tint is painted one pixel per tile and scaled up smoothly so the regions
    // fade into each other instead of forming blocks. The mask holds PAD (4) columns beyond the span (inside the map), so
    // the smoothing at a chunk's edge sees its neighbour and the chunks meet without a seam.
    const PAD = 4;
    const m0 = Math.max(0, x0 - PAD), m1 = Math.min(width, x1 + PAD);
    const mask = document.createElement('canvas');
    mask.width = m1 - m0; mask.height = height;
    const mg = mask.getContext('2d');
    for (let y = 0; y < height; y++) {
      for (let x = m0; x < m1; x++) {
        const tint = T.tint[at(x, y)] || TINT[at(x, y)];
        if (tint) { mg.fillStyle = tint; mg.fillRect(x - m0, y, 1, 1); }
      }
    }
    g.imageSmoothingEnabled = true;
    g.drawImage(mask, (m0 - x0) * TILE, 0, (m1 - m0) * TILE, height * TILE);
    const biomes = land && land.biomes;
    if (biomes) {
      // biome edges are ragged, so their tint is blurred over a couple of tiles before it is laid on
      mg.clearRect(0, 0, m1 - m0, height);
      for (let y = 0; y < height; y++) {
        for (let x = m0; x < m1; x++) {
          const tint = BIOME_TINT[(biomes[y] || '')[x]];
          if (tint) { mg.fillStyle = tint; mg.fillRect(x - m0, y, 1, 1); }
        }
      }
      const soft = document.createElement('canvas');
      soft.width = (m1 - m0) * 4; soft.height = height * 4;
      const sg = soft.getContext('2d');
      sg.filter = 'blur(5px)';
      sg.drawImage(mask, 0, 0, soft.width, soft.height);
      g.drawImage(soft, (m0 - x0) * TILE, 0, (m1 - m0) * TILE, height * TILE);
    }
    g.imageSmoothingEnabled = false;
    // grass creeps over the edges of every bare tile (dirt, sand, gravel, beach)
    for (let y = 0; y < height; y++) {
      for (let x = x0; x < x1; x++) {
        const c = at(x, y);
        if (isWater(c) || lush(x, y)) continue;
        const o = [lush(x, y - 1), lush(x + 1, y), lush(x, y + 1), lush(x - 1, y),
          lush(x + 1, y - 1), lush(x + 1, y + 1), lush(x - 1, y + 1), lush(x - 1, y - 1)];
        drawAutotile(g, sheet, hole.set, hole.inner, o, x, y, false, x0);
      }
    }
    K.drawWallEdges(g, at, width, height, span);      // rock walls stand up from the cave floor
    // small decorations baked into the ground
    const obj = img.objects;
    const decor = (variants, x, y, salt) => {
      const r = variants[hash(salt + (x - hx) + ',' + y) % variants.length].rect;
      const ox = Math.round((TILE - r[2]) / 2 + (K.hash2(x - hx, y, 31) - 0.5) * 4);
      const oy = TILE - r[3] - Math.floor(K.hash2(x - hx, y, 32) * 3);
      g.drawImage(obj, r[0], r[1], r[2], r[3], (x - x0) * TILE + ox, y * TILE + oy, r[2], r[3]);
    };
    for (let y = 0; y < height; y++) {
      for (let x = x0; x < x1; x++) {
        const c = at(x, y);
        const roll = K.hash2(x - hx, y, 30);
        if (isBeach(x, y)) continue;
        if ((c === 'g' && roll < 0.2) || (c === 'f' && roll < 0.32)) decor(T.decor.variants, x, y, 'd');
        else if (c === 'r' && roll < 0.3) decor(T.pebbles.variants, x, y, 'p');
      }
    }
    return cv;
  }

  /* --------------------------------------------------------------- objects */
  const BERRIES = [[0.3, 0.32], [0.64, 0.26], [0.5, 0.56], [0.76, 0.52], [0.24, 0.62]];

  /** Draws a sprite rect bottom-centred on the tile at (dx, dy) with tile size ts. */
  function drawRect(ctx, sheet, r, dx, dy, ts, dyPx) {
    const p = ts / TILE;
    const w = r[2] * p, h = r[3] * p;
    const x = Math.round(dx + (ts - w) / 2);
    const y = Math.round(dy + ts - h - (dyPx || 0) * p);
    ctx.drawImage(sheet, r[0], r[1], r[2], r[3], x, y, w, h);
    return { x, y, w, h, p };
  }

  /** Farm animals use the same 24x4 layout as characters; anim = { dir, moving }. */
  function drawAnimal(ctx, obj, dx, dy, ts, t, anim) {
    const A = M.animals;
    const spec = A[obj.kind];
    const sheet = img[spec.sheets[hash(obj.id) % spec.sheets.length]];
    const [fw, fh] = spec.frame;
    const n = A.framesPerDirection;
    const a = anim || {};
    const d = Math.max(0, A.directions.indexOf(a.dir || 'down'));
    const row = a.moving ? A.rows.walk : A.rows.idle;
    const speed = a.moving ? 120 : 220;
    const f = Math.floor((t + hash(obj.id) % 1000) / speed) % n;
    const p = ts / TILE;
    const w = fw * p, h = fh * p;
    ctx.drawImage(sheet, (d * n + f) * fw, row * fh, fw, fh, Math.round(dx + (ts - w) / 2), Math.round(dy + ts - h + p), w, h);
  }

  // own keys only: a kind like "constructor" must not find Object.prototype
  const own_ = (o, k) => (o && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : null);

  /** A wishing stone: its own manifest sprite when there is one, otherwise the biggest rock cooled
   *  towards moonlight with a small glowing rune, on a pale halo with motes rising off it. */
  const cooledRocks = new Map();
  function cooledRock(sheet, r) {
    const key = r.join();
    let cv = cooledRocks.get(key);
    if (!cv) {
      cv = document.createElement('canvas');
      cv.width = r[2]; cv.height = r[3];
      const g = cv.getContext('2d');
      g.drawImage(sheet, r[0], r[1], r[2], r[3], 0, 0, r[2], r[3]);
      g.globalCompositeOperation = 'source-atop';
      g.fillStyle = 'rgba(120,150,235,0.34)';
      g.fillRect(0, 0, r[2], r[3]);
      cooledRocks.set(key, cv);
    }
    return cv;
  }

  /** A kind this skin has no sprite for: its roguelike glyph, the same one the other skins use. */
  const glyph = (ctx, obj, dx, dy, ts) => K.drawGlyph(ctx, K.kindGlyph(obj.kind, obj.id), dx, dy, ts);

  function drawWishingStone(ctx, obj, dx, dy, ts, t) {
    const own = own_(M.objects, 'wishing_stone');
    const spec = own || own_(M.objects, 'rock');
    const sheet = spec && img[spec.sheet];
    if (!sheet || !Array.isArray(spec.variants) || !spec.variants.length) return glyph(ctx, obj, dx, dy, ts);
    const seed = hash(obj.id);
    K.drawWishAura(ctx, dx + ts / 2, dy + ts, ts, t, seed);
    let b;
    if (own) {
      b = drawRect(ctx, sheet, pickVariant(own, obj.id).rect, dx, dy, ts, own.dy || 0);
    } else {
      const r = spec.variants.reduce((a, v) => (v.rect[2] * v.rect[3] > a.rect[2] * a.rect[3] ? v : a)).rect;
      b = drawRect(ctx, cooledRock(sheet, r), [0, 0, r[2], r[3]], dx, dy, ts, 0);
      // a little rune worn into the face of the stone, glowing and fading
      const p = b.p;
      const a = 0.55 + 0.35 * Math.sin(t / 1100 + (seed % 628) / 100);
      const rx = b.x + (Math.floor(r[2] / 2) - 1) * p, ry = b.y + (Math.floor(r[3] / 2) - 2) * p;
      ctx.fillStyle = `rgba(232,242,255,${a.toFixed(3)})`;
      ctx.fillRect(rx + p, ry, p, 3 * p);
      ctx.fillRect(rx, ry + p, 3 * p, p);
    }
    K.drawWishMotes(ctx, b.x + b.w / 2, b.y, ts, t, seed);
    return b;
  }

  function drawObject(ctx, obj, dx, dy, ts, t, anim) {
    const animal = own_(M.animals, obj.kind);
    if (animal && Array.isArray(animal.sheets)) return drawAnimal(ctx, obj, dx, dy, ts, t, anim);
    if (obj.kind === 'wishing_stone') return drawWishingStone(ctx, obj, dx, dy, ts, t);
    const spec = own_(M.objects, obj.kind);
    if (!spec) return glyph(ctx, obj, dx, dy, ts);
    if (spec.draw && INSECTS[spec.draw]) return INSECTS[spec.draw](ctx, obj, dx, dy, ts, t);
    if (obj.kind === 'campfire') {
      if (obj.lit === false) return drawRect(ctx, img.objects, pickVariant(spec.unlit, obj.id).rect, dx, dy, ts, 1);
      const f = spec.frames[Math.floor(t / (1000 / spec.fps) + hash(obj.id)) % spec.frames.length];
      return drawRect(ctx, img.campfire, f, dx, dy, ts, 1);
    }
    if (obj.kind === 'crop') {
      const type = spec.types[obj.crop] || spec.types[spec.default];
      const stage = Math.max(0, Math.min(type.stages.length - 1, obj.stage | 0));
      return drawRect(ctx, img[type.sheet], type.stages[stage], dx, dy, ts, 0);
    }
    if (obj.kind === 'creation') {
      const invId = inventionFor(obj);
      const cv = invId && composeInvention(invId, 0);
      if (cv) {
        // the invention's own icon, a little larger than a tile, standing on its shadow
        const p = ts / TILE;
        const size = Math.round(ts * 1.25);
        const x = Math.round(dx + (ts - size) / 2), y = Math.round(dy + ts - size - p);
        ctx.fillStyle = 'rgba(0,0,0,0.28)';
        ctx.beginPath(); ctx.ellipse(dx + ts / 2, dy + ts - 2 * p, 6 * p, 2 * p, 0, 0, Math.PI * 2); ctx.fill();
        const bob = Math.round(Math.sin(t / 600 + hash(obj.id)) * p * 0.6);
        ctx.drawImage(cv, x, y + bob, size, size);
        const sp = spec.sparkle;
        const f = sp.frames[Math.floor(t / (1000 / sp.fps) + hash(obj.id)) % sp.frames.length];
        ctx.drawImage(img[sp.sheet], f[0], f[1], f[2], f[3], x + size - 12 * p, y - 4 * p, 16 * p, 16 * p);
        return;
      }
    }
    // an entry this code can't draw (no sheet or no variants) falls back to the kind's glyph
    if (!img[spec.sheet] || !Array.isArray(spec.variants) || !spec.variants.length) return glyph(ctx, obj, dx, dy, ts);
    // a store with something in it (obj.text lists the contents) shows its full sprite; fullMatch picks one by
    // words in the contents ("fish|perch": a drying rack of fish hangs fish, not meat)
    const full = spec.full && obj.text && !/^\s*(empty|nothing)/i.test(String(obj.text));
    let fulls = full ? spec.full : null;
    if (full && spec.fullMatch) {
      const text = String(obj.text).toLowerCase();
      for (const [words, list] of Object.entries(spec.fullMatch)) if (words.split('|').some((w) => text.includes(w))) { fulls = list; break; }
    }
    const r = fulls ? fulls[hash(obj.id) % fulls.length].rect : pickVariant(spec, obj.id).rect;
    const b = drawRect(ctx, img[spec.sheet], r, dx, dy, ts, spec.dy || 0);
    if (spec.sparkle) {
      // a slow glitter over inventions so they stand out from ordinary props
      const sp = spec.sparkle;
      const f = sp.frames[Math.floor(t / (1000 / sp.fps) + hash(obj.id)) % sp.frames.length];
      const s = f[2] * b.p;
      ctx.drawImage(img[sp.sheet], f[0], f[1], f[2], f[3], Math.round(b.x + (b.w - s) / 2), Math.round(b.y - s * 0.25), s, s);
    }
    if (spec.berries) {
      const p = b.p;
      for (let i = 0; i < 4; i++) {
        const [fx, fy] = BERRIES[(hash(obj.id) + i) % BERRIES.length];
        const bx = Math.round(b.x + fx * b.w), by = Math.round(b.y + fy * b.h);
        ctx.fillStyle = '#7a1d2c';
        ctx.fillRect(bx, by + p, 2 * p, p);
        ctx.fillStyle = '#e0364d';
        ctx.fillRect(bx, by, 2 * p, p);
        ctx.fillStyle = '#ff9aa6';
        ctx.fillRect(bx, by, p, p);
      }
    }
    return b;
  }

  /* --------------------------------------------------------------- insects */
  // The packs have no insects, so they are drawn here in pixels: a few hovering bees, a fluttering butterfly, a
  // cluster of firefly sparks (their light at night is the viewer's: kinds with "glow" in their data).
  const px = (ctx, x, y, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), w, h); };
  const INSECTS = {
    bees(ctx, obj, dx, dy, ts, t) {
      const p = Math.max(1, Math.round(ts / 16));
      const seed = hash(obj.id);
      for (let i = 0; i < 3; i++) {
        const a = t / (700 + i * 90) + seed % 7 + i * 2.1;
        const x = dx + ts / 2 + Math.cos(a) * ts * 0.22 + Math.sin(a * 2.3) * ts * 0.06;
        const y = dy + ts * 0.42 + Math.sin(a * 1.7) * ts * 0.16;
        px(ctx, x - p, y, 3 * p, 2 * p, '#2a1c10');
        px(ctx, x - p, y, p, 2 * p, '#f4c430');
        px(ctx, x + p, y, p, 2 * p, '#f4c430');
        if (Math.floor(t / 60 + i) % 2) px(ctx, x, y - p, p, p, 'rgba(236,244,255,0.9)');
      }
    },
    butterfly(ctx, obj, dx, dy, ts, t) {
      const p = Math.max(1, Math.round(ts / 16));
      const seed = hash(obj.id);
      const wing = ['#f08a3a', '#6ab0ff', '#f2f0ea'][seed % 3], dark = ['#8a3a10', '#24508a', '#8a8478'][seed % 3];
      const a = t / 1500 + seed % 11;
      const x = dx + ts / 2 + Math.sin(a) * ts * 0.25, y = dy + ts * 0.4 + Math.sin(a * 2) * ts * 0.12;
      const open = Math.floor(t / 140 + seed) % 3 !== 0;
      px(ctx, x, y - p, p, 3 * p, '#2a1c10');                       // body
      if (open) {
        px(ctx, x - 2 * p, y - 2 * p, 2 * p, 2 * p, wing); px(ctx, x + p, y - 2 * p, 2 * p, 2 * p, wing);
        px(ctx, x - 2 * p, y, 2 * p, p, dark); px(ctx, x + p, y, 2 * p, p, dark);
      } else {
        px(ctx, x - p, y - 2 * p, p, 2 * p, wing); px(ctx, x + p, y - 2 * p, p, 2 * p, wing);
      }
    },
    fireflies(ctx, obj, dx, dy, ts, t) {
      const p = Math.max(1, Math.round(ts / 16));
      const seed = hash(obj.id);
      for (let i = 0; i < 4; i++) {
        const a = t / (1300 + i * 170) + (seed % 13) + i * 1.7;
        const k = 0.5 + 0.5 * Math.sin(t / (420 + i * 60) + i * 2 + seed);
        const x = dx + ts / 2 + Math.cos(a) * ts * 0.3, y = dy + ts * 0.45 + Math.sin(a * 1.3) * ts * 0.25;
        ctx.fillStyle = `rgba(216,255,112,${(0.25 + 0.75 * k).toFixed(2)})`;
        ctx.fillRect(Math.round(x), Math.round(y), p, p);
      }
    },
  };

  /* ------------------------------------------------------------ characters */
  const C = () => M.characters;
  const DIRS = { right: 0, up: 1, left: 2, down: 3 };
  const composed = new Map();            // creature id -> canvas (384 x 96)

  function layerCell(layer, index) {
    const L = C()[layer];
    const [cw, ch] = C().cell;
    return [(index % L.perRow) * cw, Math.floor(index / L.perRow) * ch, cw, ch];
  }

  /** The generator recipe for a creature: deterministic from its id. */
  function recipe(id) {
    const h = (salt) => hash(id + ':' + salt);
    const r = {
      bodies: h('body') % C().bodies.count,
      eyes: h('eyes') % C().eyes.count,
      outfits: h('outfit') % C().outfits.count,
      hairstyles: h('hair') % C().hairstyles.count,
      accessories: (h('acc') % 1000) / 1000 < C().accessoryChance ? h('accN') % C().accessories.count : -1,
    };
    return r;
  }

  function characterSheet(id) {
    let cv = composed.get(id);
    if (cv) return cv;
    const [cw, ch] = C().cell;
    cv = document.createElement('canvas');
    cv.width = cw; cv.height = ch;
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    const r = recipe(id);
    for (const layer of C().layers) {
      const i = r[layer];
      if (i < 0) continue;
      const [sx, sy] = layerCell(layer, i);
      g.drawImage(img['ch_' + layer], sx, sy, cw, ch, 0, 0, cw, ch);
    }
    composed.set(id, cv);
    return cv;
  }

  /** opts: { dir, moving, t, dim, asleep } — feet at the bottom of the tile. */
  function drawCreature(ctx, cre, dx, dy, ts, opts) {
    const o = opts || {};
    const sheet = characterSheet(cre.id);
    const [fw, fh] = C().frame;
    const n = C().framesPerDirection;
    const d = DIRS[o.dir] != null ? DIRS[o.dir] : DIRS.down;
    let sx, sy;
    if (o.asleep) {
      sx = DIRS.down * fw; sy = C().rows.static;
    } else if (o.moving) {
      sx = (d * n + Math.floor((o.t || 0) / 110) % n) * fw; sy = C().rows.walk;
    } else {
      sx = (d * n + Math.floor(((o.t || 0) + hash(cre.id) % 997) / 190) % n) * fw; sy = C().rows.idle;
    }
    const p = ts / TILE;
    ctx.save();
    if (o.dim) { ctx.globalAlpha = 0.6; ctx.filter = 'grayscale(0.7) brightness(0.85)'; }
    if (o.asleep) ctx.globalAlpha *= 0.85;
    ctx.drawImage(sheet, sx, sy, fw, fh, Math.round(dx), Math.round(dy + ts - fh * p), fw * p, fh * p);
    ctx.restore();
  }

  function creatureBadge(cre, px) {
    const dpr = window.devicePixelRatio || 1;
    const cv = document.createElement('canvas');
    cv.width = Math.round(px * dpr); cv.height = Math.round(px * dpr);
    cv.style.width = px + 'px'; cv.style.height = px + 'px';
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    const sheet = characterSheet(cre.id);
    const [fw, fh] = C().frame;
    // head and shoulders of the front-facing frame, scaled to fill the badge
    const crop = [DIRS.down * fw, 6, fw, 18];
    const s = Math.floor(cv.height / crop[3]) || 1;
    const w = crop[2] * s, h = crop[3] * s;
    g.drawImage(sheet, crop[0], crop[1], crop[2], crop[3], Math.round((cv.width - w) / 2), Math.round((cv.height - h) / 2), w, h);
    return cv;
  }

  /* ------------------------------------------------------------- inventions */
  // Creatures invent new items. Each invention gets an icon composed from its
  // ingredients' icons (recursively, since inventions can be built from
  // inventions). Composites are 32x32, like the cells of icons.png: the main
  // ingredient at full size, up to two more as half-size badges, a bowl for
  // food, a plinth for placeable things, and a gold sparkle.
  const inventions = new Map();          // id -> record from /api/inventions
  const invByName = new Map();           // lower-case name -> id
  const composite = new Map();           // id -> canvas (null while unknown)
  const compositeURL = new Map();
  const BASIC = new Set(['stick', 'log', 'stone', 'plant_fiber', 'berries', 'sand', 'clay', 'water', 'flint']);
  // items without a LimeZu icon borrow a tinted Kenney glyph so they can still appear in a composite
  const KENNEY_ITEM = {
    stone_knife: [32, 6, '#cfc8bd'], stone_pickaxe: [43, 5, '#cfc8bd'], copper_pickaxe: [43, 5, '#d0874e'],
    copper_ingot: [32, 10, '#d0874e'], iron_ingot: [32, 10, '#aab4c4'], paper: [33, 15, '#efe6d2'],
  };

  function setInventions(list) {
    inventions.clear(); invByName.clear(); composite.clear(); compositeURL.clear();
    for (const inv of list || []) {
      if (!inv || !inv.id) continue;
      inventions.set(inv.id, inv);
      if (inv.name) invByName.set(String(inv.name).toLowerCase(), inv.id);
    }
  }

  /** 32x32 canvas for any item id: atlas icon, composed invention, or tinted Kenney glyph. */
  /** An item's icon cell: { sheet, rect } from icons.items, or from icons.more (the living world's items). */
  function iconRect(id) {
    if (!M || !M.icons) return null;
    const r = own_(M.icons.items, id);
    if (r) return { sheet: 'icons', rect: r };
    const more = M.icons.more;
    const r2 = more && own_(more.items, id);
    return r2 && img[more.sheet] ? { sheet: more.sheet, rect: r2 } : null;
  }

  function itemCell(id, depth) {
    const ir = iconRect(id);
    if (ir) {
      const r = ir.rect;
      const cv = document.createElement('canvas');
      cv.width = 32; cv.height = 32;
      cv.getContext('2d').drawImage(img[ir.sheet], r[0], r[1], r[2], r[3], 0, 0, 32, 32);
      return cv;
    }
    if (inventions.has(id)) return composeInvention(id, depth + 1);
    const k = KENNEY_ITEM[id];
    const glyph = k && K.glyphCanvas(k[0], k[1], k[2]);
    if (!glyph) return null;
    const cv = document.createElement('canvas');
    cv.width = 32; cv.height = 32;
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    g.drawImage(glyph, 0, 0, 32, 32);
    return cv;
  }

  /** Draws `src` with a 1px dark outline so overlapping pieces stay readable. */
  function drawOutlined(g, src, x, y, size, mirror) {
    const tmp = document.createElement('canvas');
    tmp.width = 32; tmp.height = 32;
    const t = tmp.getContext('2d');
    t.imageSmoothingEnabled = false;
    if (mirror) { t.translate(32, 0); t.scale(-1, 1); }
    t.drawImage(src, 0, 0, 32, 32);
    const sil = document.createElement('canvas');
    sil.width = 32; sil.height = 32;
    const sg = sil.getContext('2d');
    sg.drawImage(tmp, 0, 0);
    sg.globalCompositeOperation = 'source-in';
    sg.fillStyle = '#24140c';
    sg.fillRect(0, 0, 32, 32);
    for (const [ox, oy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) g.drawImage(sil, x + ox, y + oy, size, size);
    g.drawImage(tmp, x, y, size, size);
  }

  const px2 = (g, color, x, y, w, h) => { g.fillStyle = color; g.fillRect(x, y, w, h); };

  function drawBowl(g) {
    // a small wooden bowl drawn in 2x pixels, in front of the food
    px2(g, '#24140c', 3, 19, 26, 2); px2(g, '#24140c', 3, 21, 2, 4); px2(g, '#24140c', 27, 21, 2, 4);
    px2(g, '#24140c', 5, 25, 2, 2); px2(g, '#24140c', 25, 25, 2, 2); px2(g, '#24140c', 7, 27, 18, 2);
    px2(g, '#d79a5e', 5, 21, 22, 2);
    px2(g, '#a8653a', 5, 23, 22, 2); px2(g, '#8a4f2c', 7, 25, 18, 2);
    px2(g, '#f0c08a', 7, 21, 6, 1);
  }

  function drawPlinth(g) {
    px2(g, '#24140c', 3, 25, 26, 7);
    px2(g, '#c9bca8', 4, 26, 24, 2);
    px2(g, '#968a7a', 4, 28, 24, 3);
    px2(g, '#e3d8c6', 5, 26, 6, 1);
  }

  function drawSparkle(g, x, y) {
    px2(g, '#4a2e06', x + 2, y, 4, 8); px2(g, '#4a2e06', x, y + 2, 8, 4);
    px2(g, '#ffd75e', x + 3, y + 1, 2, 6); px2(g, '#ffd75e', x + 1, y + 3, 6, 2);
    px2(g, '#fff6c8', x + 3, y + 3, 2, 2);
  }

  function composeInvention(id, depth) {
    if (composite.has(id)) return composite.get(id);
    const inv = inventions.get(id);
    if (!inv || (depth || 0) > 4) return null;
    composite.set(id, null);                     // guards against cycles while composing
    const inputs = Object.entries(inv.inputs || {});
    // The most distinctive ingredient leads (inventions, then crafted things,
    // then raw materials). A placeable structure is led by its bulk material.
    const score = (k) => (k.startsWith('inv_') ? 4 : BASIC.has(k) ? 1 : iconRect(k) ? 3 : 2);
    if (inv.placeable) inputs.sort((a, b) => (b[1] || 0) - (a[1] || 0) || score(b[0]) - score(a[0]) || (a[0] < b[0] ? -1 : 1));
    else inputs.sort((a, b) => score(b[0]) - score(a[0]) || (b[1] || 0) - (a[1] || 0) || (a[0] < b[0] ? -1 : 1));
    const cells = [];
    for (const [k] of inputs) {
      const c = itemCell(k, depth || 0);
      if (c) cells.push(c);
      if (cells.length === 3) break;
    }
    if (!cells.length) { composite.delete(id); return null; }
    const cv = document.createElement('canvas');
    cv.width = 32; cv.height = 32;
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    const h = hash(id);
    const mirror = !!(h & 1);
    const [a, b, c] = cells;
    // Pieces are drawn at exact scales only (32 = the 2x icon art, 16 = 1x) so pixels stay crisp.
    if (inv.food > 0) {
      // food sits in a little bowl
      drawOutlined(g, a, 3, 8, 16, mirror);
      if (b) drawOutlined(g, b, 13, 6, 16, !mirror);
      drawBowl(g);
      drawSparkle(g, 24, 0);
    } else if (inv.placeable) {
      // structures stack their parts like a little totem on a plinth: bulk material at the base
      if (b) drawOutlined(g, b, 8, -1, 16, mirror);
      drawOutlined(g, a, 8, 10, 16, mirror);
      drawPlinth(g);
      drawSparkle(g, 0, 0);
    } else if (inv.tool) {
      // the body leans in from the bottom-left with the next part as its head
      drawOutlined(g, a, -5, 5, 32, false);
      if (b) drawOutlined(g, b, 16, 0, 16, false);
      drawSparkle(g, 0, 0);
    } else {
      drawOutlined(g, a, -4, 4, 32, mirror);
      if (b) drawOutlined(g, b, 16, 0, 16, false);
      if (c) drawOutlined(g, c, 16, 16, 16, false);
      drawSparkle(g, 0, 0);
    }
    composite.set(id, cv);
    return cv;
  }

  function inventionFor(obj) {
    const key = obj.item || obj.invention;
    if (key && inventions.has(key)) return key;
    if (obj.label) return invByName.get(String(obj.label).toLowerCase()) || null;
    return null;
  }

  /* ------------------------------------------------------------------ icons */
  /** CSS for an item icon of `px` size, or null when the manifest has none. */
  function iconStyle(itemId, px) {
    if (!M || !itemId) return null;
    const ir = iconRect(itemId);
    const r = ir && ir.rect;
    if (!r) {
      const cv = inventions.has(itemId) ? composeInvention(itemId, 0) : null;
      if (!cv) return null;
      let url = compositeURL.get(itemId);
      if (!url) { url = cv.toDataURL(); compositeURL.set(itemId, url); }
      return `background-image:url(${url});background-position:0 0;background-size:${px}px ${px}px`;
    }
    const s = px / 32;
    const sheet = img[ir.sheet];
    return `background-image:url(${BASE}${M.sheets[ir.sheet]}${VQ});background-position:${-r[0] * s}px ${-r[1] * s}px;` +
      `background-size:${sheet.naturalWidth * s}px ${sheet.naturalHeight * s}px`;
  }

  /* --------------------------------------------------------------------- ui */
  // Modern User Interface pieces from the manifest ("ui"): each becomes its own small image (CSS border-image
  // can't cut a sheet), published as CSS variables --lz-<piece> with the html class "lz-ui"; and the speech
  // bubbles on the map are drawn as 9-slices of the "button" piece. The class (which turns on the whole LimeZu
  // chrome in style.css) needs every piece the chrome uses: with an older build, or none, the chrome stays as it is.
  const UI_NEEDS = ['panel', 'board', 'well', 'slot', 'button', 'buttonDown', 'tab', 'tabOn', 'pillGold', 'skyFrame',
    'skyButton', 'skyButtonDown', 'ibBlank', 'ibSound', 'ibMute', 'ibMusic', 'ibMusicOff', 'ibSliders', 'ibRight', 'ibLeft',
    'ibPlus', 'ibMinus'];
  const UI = { pieces: {}, ok: false };
  function buildUI() {
    const spec = M.ui;
    const sheet = spec && img[spec.sheet];
    if (!sheet) return;
    for (const [name, piece] of Object.entries(spec)) {
      if (!piece || !Array.isArray(piece.rect)) continue;
      const [x, y, w, h] = piece.rect;
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      cv.getContext('2d').drawImage(sheet, x, y, w, h, 0, 0, w, h);
      UI.pieces[name] = { canvas: cv, slice: piece.slice || 4, url: cv.toDataURL() };
    }
    UI.ok = UI_NEEDS.every((n) => UI.pieces[n]);
  }

  /** Publishes the UI pieces to CSS (or takes them back when another skin is chosen). */
  function applyUI(root, on) {
    root.classList.toggle('lz-ui', !!(on && UI.ok));
    if (!UI.ok) return;
    for (const [name, p] of Object.entries(UI.pieces)) {
      root.style.setProperty('--lz-' + name.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()), `url(${p.url})`);
    }
  }

  /** Draws a UI piece as a 9-slice box at (x, y, w, h), with its pixels scaled by `scale`. */
  function drawPiece(ctx, name, x, y, w, h, scale) {
    const p = UI.pieces[name];
    if (!p) return false;
    const cv = p.canvas, s = p.slice, k = scale || 2, d = s * k;
    const sw = cv.width, sh = cv.height;
    const cols = [[0, s, 0, d], [s, sw - 2 * s, d, w - 2 * d], [sw - s, s, w - d, d]];
    const rows = [[0, s, 0, d], [s, sh - 2 * s, d, h - 2 * d], [sh - s, s, h - d, d]];
    for (const [sx, sW, dx, dW] of cols) {
      for (const [sy, sH, dy, dH] of rows) {
        if (dW > 0 && dH > 0) ctx.drawImage(cv, sx, sy, sW, sH, Math.round(x + dx), Math.round(y + dy), Math.ceil(dW), Math.ceil(dH));
      }
    }
    return true;
  }

  /* ----------------------------------------------------------------- roofs (see roofs.js)
   * The Serene Village roofs, a 9-slice per design in the manifest ("roofs"): the corners and edges are kept, the
   * middle is tiled to the building's rectangle. Painted once per design and size, then drawn scaled. */
  const roofCache = new Map();

  function paintRoof(g, sheet, spec, W, H) {
    const [rx, ry, rw, rh] = spec.rect, [l, r, t, b] = M.roofs.slice;
    const mw = rw - l - r, mh = rh - t - b;
    const blit = (sx, sy, sw, sh, dx, dy) => g.drawImage(sheet, rx + sx, ry + sy, sw, sh, dx, dy, sw, sh);
    for (let y = t; y < H - b; y += mh) {
      const ch = Math.min(mh, H - b - y);
      blit(0, t, l, ch, 0, y);
      blit(rw - r, t, r, ch, W - r, y);
      for (let x = l; x < W - r; x += mw) {
        const cw = Math.min(mw, W - r - x);
        blit(l, t, cw, ch, x, y);
        if (y === t) { blit(l, 0, cw, t, x, 0); blit(l, rh - b, cw, b, x, H - b); }
      }
    }
    blit(0, 0, l, t, 0, 0); blit(rw - r, 0, r, t, W - r, 0);
    blit(0, rh - b, l, b, 0, H - b); blit(rw - r, rh - b, r, b, W - r, H - b);
  }

  function drawRoof(ctx, b, x, y, w, h, ts, now) {
    const roofs = M && ready && M.roofs, sheet = roofs && img[roofs.sheet];
    const spec = roofs && roofs.designs && (own_(roofs.designs, b.design) || own_(roofs.designs, roofs.default));
    if (!sheet || !spec) return K.drawRoof(ctx, b, x, y, w, h, ts, now);
    const W = (b.x1 - b.x0 + 1) * TILE, H = (b.y1 - b.y0 + 1) * TILE, key = b.design + '|' + W + '|' + H;
    let cv = roofCache.get(key);
    if (!cv) {
      if (roofCache.size > 48) roofCache.clear();
      cv = document.createElement('canvas');
      cv.width = W; cv.height = H;
      paintRoof(cv.getContext('2d'), sheet, spec, W, H);
      roofCache.set(key, cv);
    }
    ctx.drawImage(cv, Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  window.SwarmLimeZu = {
    name: 'limezu',
    credit: 'Art: LimeZu (limezu.itch.io)',
    load, get ready() { return ready; }, get manifest() { return M; },
    spriteTopTiles: 1.6,       // how far above the tile bottom a character's head reaches
    drawsWater: false,
    renderTerrain, drawObject, drawCreature, creatureBadge, drawRoof, iconStyle, setInventions,
    inventionId: (name) => invByName.get(String(name || '').toLowerCase()) || null,
    objectName: K.objectName, terrainName: K.terrainName,
    hasObject: (kind) => !!(M && (own_(M.objects, kind) || own_(M.animals, kind))),
    /** Where smoke leaves a station's sprite (fractions of its box), from the manifest; null when it smokes not. */
    smokeAt: (kind) => { const o = M && own_(M.objects, kind); return o && Array.isArray(o.smoke) ? o.smoke : null; },
    get ui() { return UI.pieces.button ? UI : null; }, applyUI, drawPiece,   // the map's speech bubbles need only the button
  };
})();
