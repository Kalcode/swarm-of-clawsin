/* Swarm World viewer: LimeZu skin (default when web/assets/limezu/ is present).
 *
 * Art: LimeZu (limezu.itch.io): Modern Exteriors, Modern Interiors, Modern
 * Farm and Serene Village, 16x16 versions. The packs are licensed to the user
 * and must not be redistributed, so web/assets/limezu/ is gitignored; when it
 * is missing the viewer falls back to the Kenney skin in tiles.js.
 *
 * Everything is driven by web/assets/limezu/manifest.json: kind/item -> sheet
 * + rect (+ frames). New kinds only need a manifest entry. Kinds without one
 * are drawn with the Kenney art so they still show up.
 */
(function () {
  'use strict';

  const BASE = 'assets/limezu/';
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
      const r = await fetch(BASE + 'manifest.json', { cache: 'no-cache' });
      if (!r.ok) return false;
      M = await r.json();
      const jobs = [];
      for (const [name, file] of Object.entries(M.sheets)) jobs.push(loadImage(BASE + file).then((i) => { img[name] = i; }));
      for (const layer of M.characters.layers) {
        jobs.push(loadImage(BASE + M.characters[layer].src).then((i) => { img['ch_' + layer] = i; }));
      }
      for (const kind of ANIMAL_KINDS) {
        for (const file of (M.animals && M.animals[kind] ? M.animals[kind].sheets : [])) {
          jobs.push(loadImage(BASE + file).then((i) => { img[file] = i; }));
        }
      }
      await Promise.all(jobs);
      ready = true;
      return true;
    } catch (err) {
      console.info('[limezu] skin unavailable, using Kenney art:', err.message);
      return false;
    }
  }

  const hash = (s) => K.hashStr(s);
  const ANIMAL_KINDS = ['chicken', 'sheep', 'cow'];
  const pickVariant = (spec, id) => spec.variants[hash(id) % spec.variants.length];

  /* --------------------------------------------------------------- terrain */
  const isWater = (c) => c === 'w' || c === 'W';
  const isGrassy = (c) => c === 'g' || c === 'f';

  /** Draws one tile of a 3x3 + inner-corner autotile set, quarter by quarter
   *  (8x8 each), so thin strips and single-tile peninsulas get edges on every
   *  side. o = [n, e, s, w, ne, se, sw, nw]: true where the neighbour is the
   *  "other" terrain. Quarters with nothing to show are skipped unless `fill`. */
  function drawAutotile(g, sheet, set, inner, o, x, y, fill) {
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
        g.drawImage(sheet, sx + qx * H, sy + qy * H, H, H, x * TILE + qx * H, y * TILE + qy * H, H, H);
      }
    }
    return true;
  }

  function renderTerrain(tiles, width, height) {
    const cv = document.createElement('canvas');
    cv.width = width * TILE;
    cv.height = height * TILE;
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    const T = M.terrain;
    const sheet = img[T.sheet];
    const at = (x, y) => {
      const cx = Math.max(0, Math.min(width - 1, x)), cy = Math.max(0, Math.min(height - 1, y));
      return (tiles[cy] && tiles[cy][cx]) || 'g';
    };
    const blit = (rect, x, y) => g.drawImage(sheet, rect[0], rect[1], TILE, TILE, x * TILE, y * TILE, TILE, TILE);
    const near = (x, y, pred) => [
      pred(at(x, y - 1)), pred(at(x + 1, y)), pred(at(x, y + 1)), pred(at(x - 1, y)),
      pred(at(x + 1, y - 1)), pred(at(x + 1, y + 1)), pred(at(x - 1, y + 1)), pred(at(x - 1, y - 1)),
    ];
    const shore = T.autotiles.shore, hole = T.autotiles.grassHole;
    // land touching water is drawn as beach; everything else keeps its own ground
    const beach = new Uint8Array(width * height);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (!isWater(at(x, y)) && near(x, y, isWater).some(Boolean)) beach[y * width + x] = 1;
      }
    }
    const isBeach = (x, y) => beach[Math.max(0, Math.min(height - 1, y)) * width + Math.max(0, Math.min(width - 1, x))] === 1;
    const lush = (x, y) => isGrassy(at(x, y)) && !isBeach(x, y);

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const c = at(x, y);
        const flats = T.flats[c] || T.flats.g;
        blit(flats[hash(x + ',' + y) % flats.length], x, y);
        if (!isWater(c)) {
          // land touching water becomes a little beach with a foam edge
          if (isBeach(x, y)) drawAutotile(g, sheet, shore.set, shore.inner, near(x, y, isWater), x, y, true);
        }
      }
    }
    // Deep water and forest floor are darker versions of water and grass. The
    // tint is painted one pixel per tile and scaled up smoothly so the regions
    // fade into each other instead of forming blocks.
    const mask = document.createElement('canvas');
    mask.width = width; mask.height = height;
    const mg = mask.getContext('2d');
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const tint = T.tint[at(x, y)];
        if (tint) { mg.fillStyle = tint; mg.fillRect(x, y, 1, 1); }
      }
    }
    g.imageSmoothingEnabled = true;
    g.drawImage(mask, 0, 0, width * TILE, height * TILE);
    g.imageSmoothingEnabled = false;
    // grass creeps over the edges of every bare tile (dirt, sand, gravel, beach)
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const c = at(x, y);
        if (isWater(c) || lush(x, y)) continue;
        const o = [lush(x, y - 1), lush(x + 1, y), lush(x, y + 1), lush(x - 1, y),
          lush(x + 1, y - 1), lush(x + 1, y + 1), lush(x - 1, y + 1), lush(x - 1, y - 1)];
        drawAutotile(g, sheet, hole.set, hole.inner, o, x, y, false);
      }
    }
    // small decorations baked into the ground
    const obj = img.objects;
    const decor = (variants, x, y, salt) => {
      const r = variants[hash(salt + x + ',' + y) % variants.length].rect;
      const ox = Math.round((TILE - r[2]) / 2 + (K.hash2(x, y, 31) - 0.5) * 4);
      const oy = TILE - r[3] - Math.floor(K.hash2(x, y, 32) * 3);
      g.drawImage(obj, r[0], r[1], r[2], r[3], x * TILE + ox, y * TILE + oy, r[2], r[3]);
    };
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const c = at(x, y);
        const roll = K.hash2(x, y, 30);
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

  function drawObject(ctx, obj, dx, dy, ts, t, anim) {
    if (M.animals && M.animals[obj.kind]) return drawAnimal(ctx, obj, dx, dy, ts, t, anim);
    const spec = M.objects[obj.kind];
    if (!spec) return K.drawObject(ctx, obj, dx, dy, ts, t);
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
    // a store with something in it (obj.text lists the contents) shows its full sprite
    const full = spec.full && obj.text && !/^\s*(empty|nothing)/i.test(String(obj.text));
    const r = full ? spec.full[hash(obj.id) % spec.full.length].rect : pickVariant(spec, obj.id).rect;
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
  function itemCell(id, depth) {
    const r = M.icons.items[id];
    if (r) {
      const cv = document.createElement('canvas');
      cv.width = 32; cv.height = 32;
      cv.getContext('2d').drawImage(img.icons, r[0], r[1], r[2], r[3], 0, 0, 32, 32);
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
    const score = (k) => (k.startsWith('inv_') ? 4 : BASIC.has(k) ? 1 : M.icons.items[k] ? 3 : 2);
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
    const r = M.icons.items[itemId];
    if (!r) {
      const cv = inventions.has(itemId) ? composeInvention(itemId, 0) : null;
      if (!cv) return null;
      let url = compositeURL.get(itemId);
      if (!url) { url = cv.toDataURL(); compositeURL.set(itemId, url); }
      return `background-image:url(${url});background-position:0 0;background-size:${px}px ${px}px`;
    }
    const s = px / 32;
    const sheet = img.icons;
    return `background-image:url(${BASE}${M.sheets.icons});background-position:${-r[0] * s}px ${-r[1] * s}px;` +
      `background-size:${sheet.naturalWidth * s}px ${sheet.naturalHeight * s}px`;
  }

  window.SwarmLimeZu = {
    name: 'limezu',
    credit: 'Art: LimeZu (limezu.itch.io)',
    load, get ready() { return ready; }, get manifest() { return M; },
    spriteTopTiles: 1.6,       // how far above the tile bottom a character's head reaches
    drawsWater: false,
    renderTerrain, drawObject, drawCreature, creatureBadge, iconStyle, setInventions,
    inventionId: (name) => invByName.get(String(name || '').toLowerCase()) || null,
    objectName: K.objectName, terrainName: K.terrainName,
    hasObject: (kind) => !!(M && (M.objects[kind] || (M.animals && M.animals[kind]))),
  };
})();
