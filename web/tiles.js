/* Swarm World viewer: sprite sheet, tile/object/creature mapping and drawing.
 *
 * Art: Kenney "1-Bit Pack" (CC0), colored, transparent, packed variant:
 * 768 x 352 px, 48 x 22 tiles of 16 px, no spacing. Coordinates below are
 * [column, row] on that sheet. If the image fails to load every draw call
 * falls back to simple procedural shapes so the viewer never breaks.
 */
(function () {
  'use strict';

  const TILE = 16;
  const SHEET_SRC = 'assets/kenney-1bit/colored_transparent_packed.png';
  const SHEET_COLS = 48;
  const SHEET_ROWS = 22;

  // The sheet's own palette, reused by the UI so map and chrome agree.
  const PAL = {
    plum: '#472d3c', rose: '#7a444a', red: '#e6482e', brown: '#bf7958',
    green: '#38d973', gold: '#f4b41b', blue: '#3cacd7', bone: '#cfc6b8',
  };

  /* ---------------------------------------------------------------- terrain */
  // base: three shades picked per tile by hash; glyph: sparse overlay sprite.
  const TERRAIN = {
    g: { name: 'grass', base: ['#1e2c21', '#1f2e22', '#202f23'], glyphs: [[5, 0], [6, 0], [7, 0]], tint: '#38d973', alpha: 0.2, density: 0.34 },
    f: { name: 'forest floor', base: ['#18241a', '#19251b', '#1a261c'], glyphs: [[0, 2], [5, 0]], tint: '#2a7a45', alpha: 0.4, density: 0.2 },
    d: { name: 'dirt', base: ['#342520', '#352621', '#362722'], glyphs: [[1, 0], [2, 0]], tint: '#7a444a', alpha: 0.26, density: 0.3 },
    s: { name: 'sand', base: ['#5c4b34', '#5e4d35', '#604f37'], glyphs: [[1, 0], [2, 0]], tint: '#857050', alpha: 0.35, density: 0.3 },
    r: { name: 'rocky ground', base: ['#2a262c', '#2b272d', '#2c282e'], glyphs: [[3, 0], [4, 0]], tint: '#4f4853', alpha: 0.6, density: 0.4 },
    w: { name: 'water', base: ['#1b4a66', '#1c4c69', '#1e4f6c'], water: true },
    W: { name: 'deep water', base: ['#11314a', '#12334c', '#13354f'], water: true, deep: true },
    // the deep: rock, the cave floor between it, still dark pools; and the land dug on the surface
    R: { name: 'rock wall', base: ['#2c272d', '#2e292f', '#302a31'], glyphs: [[3, 0], [4, 0]], tint: '#5a5160', alpha: 0.5, density: 0.8 },
    c: { name: 'cave floor', base: ['#17151a', '#18161b', '#19171c'], glyphs: [[1, 0], [2, 0]], tint: '#4a4452', alpha: 0.35, density: 0.22 },
    u: { name: 'cave water', base: ['#0e2a30', '#0f2c32', '#102e34'], water: true },
    t: { name: 'trench', base: ['#271a14', '#281b15', '#291c16'], glyphs: [[1, 0], [2, 0]], tint: '#5e3e30', alpha: 0.3, density: 0.25 },
    h: { name: 'pit', base: ['#1a110d', '#1b120e', '#1c130f'], glyphs: [[1, 0], [2, 0]], tint: '#4a3024', alpha: 0.3, density: 0.18 },
    O: { name: 'open pit', base: ['#060405', '#070506', '#080607'], glyphs: [], density: 0 },
  };

  /* ---------------------------------------------------------------- objects */
  const OBJECTS = {
    tree: { name: 'tree', s: [4, 2], alt: [[5, 1]] },
    pine: { name: 'pine', s: [0, 1], alt: [[1, 1]], tint: '#2cc56a' },
    stump: { name: 'stump', s: [18, 6] },
    bush: { name: 'berry bush', s: [1, 2], berries: true },
    bush_empty: { name: 'bush (picked)', s: [1, 2], tint: '#3f7a52' },
    rock: { name: 'rock', s: [5, 2] },
    wishing_stone: { name: 'wishing stone', s: [5, 2], tint: '#b9c9f2', wish: true },
    copper_vein: { name: 'copper vein', s: [5, 2], tint: '#d0874e', fleck: '#f4b41b' },
    iron_vein: { name: 'iron vein', s: [5, 2], tint: '#8f9fba', fleck: '#e8eef7' },
    clay: { name: 'clay', s: [11, 15], tint: '#c27a5c' },
    campfire: { name: 'campfire', s: [14, 10], unlitTint: '#6e5a55', fire: true },
    workbench: { name: 'workbench', s: [8, 7] },
    furnace: { name: 'furnace', s: [8, 8], tint: '#b8aa98' },
    wall: { name: 'wall', s: [13, 16] },
    sign: { name: 'sign', s: [0, 7] },
    chest: { name: 'chest', s: [8, 6] },
    terminal: { name: 'terminal', s: [9, 14], screen: true },
    tablet: { name: 'tablet', s: [0, 14] },
    pile: { name: 'pile', s: [45, 4] },
    crop: { name: 'wheat', s: [15, 6], tint: '#e8c25a' },
    sapling: { name: 'sapling', s: [16, 6] },
    millstone: { name: 'millstone', s: [39, 13], tint: '#b8aa98' },
    bed: { name: 'bed', s: [5, 8] },
    door: { name: 'door', s: [8, 9] },
    chicken: { name: 'chicken', s: [25, 7] },
    sheep: { name: 'sheep', s: [29, 7], tint: '#e8e2d6' },
    cow: { name: 'cow', s: [28, 7], tint: '#c9a27e' },
    creation: { name: 'invention', s: [27, 12], tint: '#f4b41b' },
    basket: { name: 'basket', s: [46, 4], tint: '#c98a4e' },
  };

  /* ---------------------------------------------------------------- glyphs */
  // One roguelike glyph per kind: [char, color, optional colors picked per object]. The ASCII skin draws every
  // kind with it, and the other skins fall back to it for a kind they have no art for. A kind's data may set its
  // own ("glyph": {"char", "color"} in objects.json, sent in the init message's kinds), which wins over this
  // table; a kind in neither gets the first letter of its name in a neutral color.
  const GLYPHS = {
    tree: ['♣', '#5cb85a'], pine: ['♠', '#3fae7c'], stump: ['∩', '#a8774a'],
    bush: ['¥', '#4fbf5a'], bush_empty: ['¥', '#6f8f58'], sapling: ['τ', '#7fdc6e'], crop: ['ψ', '#e8c25a'],
    rock: ['●', '#a39ca6'], wishing_stone: ['◊', '#b9c9f2'], copper_vein: ['$', '#d0874e'], iron_vein: ['$', '#a6b0c2'],
    clay: ['%', '#c97c5e'], campfire: ['☼', '#ffb347'], workbench: ['π', '#c98a4e'], furnace: ['Θ', '#e6824a'],
    wall: ['#', '#bf7958'], sign: ['¶', '#d2b48c'], chest: ['Ξ', '#d09a5a'], basket: ['U', '#c98a4e'],
    terminal: ['▣', '#38d973'], tablet: ['∏', '#cfc6b8'], pile: ['&', '#c9a27e'], millstone: ['Ø', '#b8aa98'],
    bed: ['▬', '#c9a27e'], door: ['+', '#bf7958'], creation: ['✦', '#ffd75e'],
    chicken: ['c', '#f0e6d2'], sheep: ['s', '#f2efe6'], cow: ['C', '#c9a27e'],
    // nature (S1)
    flower_patch: ['*', '#e9a8f0', ['#f4e27a', '#f2f0ea', '#e9a8f0', '#b9a6f0']], picked_flowers: [':', '#7f9f5c'],
    reed_bed: ['"', '#b0bc62'], cut_reeds: ['¨', '#c8b878'], mushroom_patch: [',', '#ecd2ae'], shell_bed: ['§', '#f2d8c8'],
    driftwood: ['/', '#d8d0c0'], flint_outcrop: ['♦', '#8f96ae'],
    honeybee: ['ж', '#f4c430'], butterfly: ['Ж', '#f08a3a', ['#f08a3a', '#6ab0ff', '#f2f0ea']], firefly: ['•', '#d8ff70'],
    // food (S4)
    deer: ['d', '#c8a070'], rabbit: ['r', '#c4b4a0'], boar: ['b', '#a07a5c'], herb_patch: ['†', '#7fdc6e'],
    herb_patch_cut: ['ı', '#6a9a58'], oven: ['Ω', '#d07850'], smoker: ['⌂', '#a89078'], drying_rack: ['~', '#c99a5e'],
    well: ['O', '#9ab8d8'],
    // building (S6): its kinds' own data glyphs win over these
    hut: ['⌂', '#d0a070'], tent: ['⌂', '#c8b090'], shelter: ['⌂', '#c8a882'], bridge: ['=', '#c98a4e'],
  };
  const GLYPH_NEUTRAL = '#b9aebb';
  let KINDS = {};                        // kind -> { name, look?, glyph?, glow? }, from the init message
  const own = (o, k) => !!o && Object.prototype.hasOwnProperty.call(o, k);
  const COLOR_RE = /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%deg]+\)|[a-z]{3,20})$/i;

  /** The init message's kinds: names, look hints, glyphs and glows from the world's data. */
  function setKinds(kinds) { KINDS = kinds && typeof kinds === 'object' ? kinds : {}; }
  function kindInfo(kind) { return own(KINDS, kind) && KINDS[kind] && typeof KINDS[kind] === 'object' ? KINDS[kind] : null; }

  /** A kind's glyph { char, color }: its data's own, else this table's, else the first letter of its name. `id`
   *  picks one of a kind's colors (flowers come in several), so each object keeps its own. Never "?". */
  function kindGlyph(kind, id) {
    const info = kindInfo(kind);
    const data = info && info.glyph;
    if (data && typeof data.char === 'string' && data.char.trim() && data.char.trim() !== '?') {
      // a color too dark to read on the dark ground (the coal seam's black) is lifted a little
      return { char: [...data.char.trim()][0], color: typeof data.color === 'string' && COLOR_RE.test(data.color.trim()) ? readable(data.color.trim()) : GLYPH_NEUTRAL };
    }
    if (own(GLYPHS, kind)) {
      const g = GLYPHS[kind];
      return { char: g[0], color: g[2] && id != null ? g[2][hashStr(id) % g[2].length] : g[1] };
    }
    const name = String((info && info.name) || kind || 'thing').replace(/_/g, ' ');
    const m = name.match(/[\p{L}\p{N}]/u);
    return { char: m ? m[0] : '¤', color: GLYPH_NEUTRAL };
  }

  // Glyphs are drawn from small cached canvases (one per char, color and size), so a screen full of them is cheap.
  const glyphCache = new Map();
  const MONO = (typeof getComputedStyle === 'function' && getComputedStyle(document.documentElement).getPropertyValue('--mono').trim()) ||
    'ui-monospace, Menlo, Consolas, monospace';
  /** A canvas of `ch` in `color`, `px` device pixels high, with a dark outline when `outline`. */
  function glyphSprite(ch, color, px, outline, weight) {
    const key = ch + '|' + color + '|' + px + '|' + (outline ? 1 : 0) + '|' + (weight || 700);
    let cv = glyphCache.get(key);
    if (cv) return cv;
    if (glyphCache.size > 1600) glyphCache.clear();
    const pad = outline ? Math.max(1, Math.round(px / 10)) : 0;
    const size = Math.ceil(px * 1.25) + pad * 2;
    cv = document.createElement('canvas');
    cv.width = size; cv.height = size;
    const g = cv.getContext('2d');
    g.font = `${weight || 700} ${px}px ${MONO}`;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    const cx = size / 2, cy = size / 2 + px * 0.04;
    if (outline) {
      g.lineJoin = 'round';
      g.lineWidth = pad * 2;
      g.strokeStyle = 'rgba(8,6,12,0.85)';
      g.strokeText(ch, cx, cy);
    }
    g.fillStyle = color;
    g.fillText(ch, cx, cy);
    glyphCache.set(key, cv);
    return cv;
  }

  /** Draws a glyph centred on the tile at (dx, dy) of size ts (CSS pixels on a context scaled by the device
   *  pixel ratio). opts: { scale (of the tile, default 0.8), outline, alpha, dy (CSS px), weight }. */
  function drawGlyph(ctx, glyph, dx, dy, ts, opts) {
    const o = opts || {};
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    const px = Math.max(6, Math.round(ts * (o.scale || 0.8) * dpr));
    const cv = glyphSprite(glyph.char, glyph.color, px, o.outline !== false, o.weight);
    const w = cv.width / dpr;
    const x = Math.round((dx + ts / 2 - w / 2) * dpr) / dpr, y = Math.round((dy + ts / 2 - w / 2 + (o.dy || 0)) * dpr) / dpr;
    const a = ctx.globalAlpha;
    if (o.alpha != null) ctx.globalAlpha = a * o.alpha;
    ctx.drawImage(cv, x, y, w, w);
    ctx.globalAlpha = a;
  }

  /** How the Kenney skin draws a kind: its own sprite, or its glyph (for kinds this sheet has no art for). */
  function kenneyLook(kind) {
    return knownObject(kind) ? { type: 'sprite' } : { type: 'glyph', ...kindGlyph(kind) };
  }

  // Shared character sprites; each creature picks one by id hash and is tinted.
  const CREATURES = [[25, 0], [27, 1], [28, 1], [26, 2], [24, 3], [29, 4], [30, 3], [25, 4]];

  // UI icons rendered from the same sheet (see iconStyles()).
  const ICONS = {
    say: [36, 13], craft: [37, 7], discover: [28, 12], gather: [40, 7], fail: [40, 13],
    place: [41, 16], write: [33, 15], program: [9, 14], collapse: [38, 11], join: [43, 16],
    sleep: [47, 19], eat: [33, 18], people: [44, 16], person: [43, 16], sun: [27, 11],
    night: [29, 12], plus: [36, 20], minus: [37, 20], right: [24, 20], left: [26, 20],
    book: [45, 5], bag: [46, 4], trophy: [40, 16], gear: [45, 16], heart: [39, 10],
    target: [22, 14], dot: [21, 14], plant: [16, 6], chronicle: [45, 5], tame: [39, 10], invent: [29, 12], voice: [21, 6], rain: [22, 6], store: [46, 4], take: [45, 4], tend: [14, 10],
    wish: [36, 11], grant: [33, 10],
  };

  // Pixel font glyphs from the sheet (title text).
  function glyphFor(ch) {
    const c = ch.toUpperCase();
    if (c >= 'A' && c <= 'M') return [35 + (c.charCodeAt(0) - 65), 18];
    if (c >= 'N' && c <= 'Z') return [35 + (c.charCodeAt(0) - 78), 19];
    if (c >= '0' && c <= '9') return [35 + (c.charCodeAt(0) - 48), 17];
    return null;
  }

  /* ---------------------------------------------------------------- helpers */
  function hash2(x, y, s) {
    let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul((s | 0) + 1, 1442695041);
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  }

  // Tile looks are hashed on x - origin, the world column counted from the home map's west edge, so land laid down
  // west of it doesn't re-roll the look of the old map. The viewer sets the origin from each init.
  let originX = 0;
  function setOrigin(x) { originX = x | 0; }
  function origin() { return originX; }
  function hashAt(x, y, s) { return hash2(x - originX, y, s); }

  function hashStr(str) {
    let h = 2166136261;
    const s = String(str);
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  const probe = document.createElement('canvas').getContext('2d');
  const colorCache = new Map();
  /** Any CSS color -> [r, g, b]. */
  function rgb(color) {
    if (colorCache.has(color)) return colorCache.get(color);
    probe.fillStyle = '#cfc6b8';
    probe.fillStyle = color || '#cfc6b8';
    const v = probe.fillStyle;
    let out = [207, 198, 184];
    if (v[0] === '#') {
      out = [parseInt(v.slice(1, 3), 16), parseInt(v.slice(3, 5), 16), parseInt(v.slice(5, 7), 16)];
    } else {
      const m = v.match(/[\d.]+/g);
      if (m) out = [+m[0], +m[1], +m[2]];
    }
    colorCache.set(color, out);
    return out;
  }
  function mix(a, b, t) {
    const x = rgb(a), y = rgb(b);
    const c = (i) => Math.round(x[i] + (y[i] - x[i]) * t);
    return `rgb(${c(0)},${c(1)},${c(2)})`;
  }
  function rgba(color, alpha) {
    const c = rgb(color);
    return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
  }
  /** Lift dark colors so they stay readable on the dark UI. */
  function readable(color) {
    const c = rgb(color);
    const lum = (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;
    return lum < 0.45 ? mix(color, '#ffffff', Math.min(0.6, 0.45 - lum + 0.15)) : `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  /* ------------------------------------------------------------------ sheet */
  let sheet = null;
  let ready = false;
  const tintCache = new Map();

  function load() {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth !== SHEET_COLS * TILE || img.naturalHeight !== SHEET_ROWS * TILE) {
          console.warn('[tiles] unexpected sheet size', img.naturalWidth, img.naturalHeight);
        }
        sheet = img; ready = true; resolve(true);
      };
      img.onerror = () => { console.warn('[tiles] sprite sheet failed to load; using procedural fallback'); resolve(false); };
      img.src = SHEET_SRC;
    });
  }

  /** Returns a drawable + source rect for sheet cell [c, r], optionally tinted. */
  function sprite(c, r, tint) {
    if (!tint) return { img: sheet, sx: c * TILE, sy: r * TILE };
    const key = c + ',' + r + ',' + tint;
    let cv = tintCache.get(key);
    if (!cv) {
      cv = document.createElement('canvas');
      cv.width = TILE; cv.height = TILE;
      const g = cv.getContext('2d');
      g.drawImage(sheet, c * TILE, r * TILE, TILE, TILE, 0, 0, TILE, TILE);
      g.globalCompositeOperation = 'source-in';
      g.fillStyle = tint;
      g.fillRect(0, 0, TILE, TILE);
      tintCache.set(key, cv);
    }
    return { img: cv, sx: 0, sy: 0 };
  }

  function blit(ctx, c, r, tint, dx, dy, size, flip) {
    const s = sprite(c, r, tint);
    if (flip) {
      ctx.save();
      ctx.translate(dx + size, dy);
      ctx.scale(-1, 1);
      ctx.drawImage(s.img, s.sx, s.sy, TILE, TILE, 0, 0, size, size);
      ctx.restore();
    } else {
      ctx.drawImage(s.img, s.sx, s.sy, TILE, TILE, dx, dy, size, size);
    }
  }

  /* ---------------------------------------------------------------- terrain */
  function isWater(code) { return code === 'w' || code === 'W' || code === 'u'; }

  // biomes (init's nature rows) shade the ground: an olive marsh, a cool pine forest, grey hills, warm beach
  const BIOME_SHADE = { k: ['#3a3a12', 0.3], p: ['#0a2a2a', 0.25], h: ['#3a3440', 0.2], b: ['#5c4b34', 0.12] };

  /** Pre-renders columns span.x0..x1-1 of the map (all of it by default) at 16 px per tile; the viewer scales it.
   *  Tile looks are hashed on x - span.hx, and neighbours (shorelines, wall edges) are read from the full rows, so
   *  a chunk's edge tiles look as they do in the whole map. */
  function renderTerrain(tiles, width, height, land, span) {
    const { x0, x1, hx } = span || { x0: 0, x1: width, hx: 0 };
    const cv = document.createElement('canvas');
    cv.width = (x1 - x0) * TILE; cv.height = height * TILE;
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    const at = (x, y) => (tiles[y] && tiles[y][x]) || 'g';

    for (let y = 0; y < height; y++) {
      for (let x = x0; x < x1; x++) {
        const code = at(x, y);
        const t = TERRAIN[code] || TERRAIN.g;
        const px = (x - x0) * TILE, py = y * TILE;
        g.fillStyle = t.base[Math.floor(hash2(x - hx, y, 3) * t.base.length)];
        const shade = !t.water && land && land.biomes && BIOME_SHADE[(land.biomes[y] || '')[x]];
        if (shade) g.fillStyle = mix(g.fillStyle, shade[0], shade[1]);
        g.fillRect(px, py, TILE, TILE);

        if (t.water) continue;
        if (t.density && hash2(x - hx, y, 1) < t.density) {
          g.globalAlpha = t.alpha;
          if (ready) {
            const [c, r] = t.glyphs[Math.floor(hash2(x - hx, y, 2) * t.glyphs.length)];
            blit(g, c, r, t.tint, px, py, TILE, hash2(x - hx, y, 4) < 0.5);
          } else {
            g.fillStyle = t.tint;
            for (let i = 0; i < 4; i++) {
              g.fillRect(px + Math.floor(hash2(x - hx, y, 10 + i) * 14), py + Math.floor(hash2(x - hx, y, 20 + i) * 14), 2, 1 + (i & 1));
            }
          }
          g.globalAlpha = 1;
        }
      }
    }

    // Shorelines: a pale lip where water meets land, a darker step into deep water.
    for (let y = 0; y < height; y++) {
      for (let x = x0; x < x1; x++) {
        const code = at(x, y);
        if (!isWater(code)) continue;
        const px = (x - x0) * TILE, py = y * TILE;
        const edges = [[0, -1], [1, 0], [0, 1], [-1, 0]];
        for (const [dx, dy] of edges) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
          const n = at(nx, ny);
          let color = null;
          if (!isWater(n)) color = 'rgba(160,214,236,0.38)';
          else if (code === 'W' && n === 'w') color = 'rgba(60,172,215,0.22)';
          if (!color) continue;
          g.fillStyle = color;
          if (dy === -1) g.fillRect(px, py, TILE, 1);
          if (dy === 1) g.fillRect(px, py + TILE - 1, TILE, 1);
          if (dx === -1) g.fillRect(px, py, 1, TILE);
          if (dx === 1) g.fillRect(px + TILE - 1, py, 1, TILE);
        }
      }
    }
    drawWallEdges(g, at, width, height, span);
    return cv;
  }

  /** Rock walls stand up from the cave floor: a pale rim where a wall meets open ground, and the wall's shadow on
   *  the ground south of it. On a pre-rendered terrain canvas of 16 px tiles holding columns x0..x1-1 (`span`, all by
   *  default); `at(x, y)` gives a tile's code. */
  function drawWallEdges(g, at, width, height, span) {
    const { x0, x1 } = span || { x0: 0, x1: width };
    const wall = (x, y) => x < 0 || y < 0 || x >= width || y >= height || at(x, y) === 'R';
    for (let y = 0; y < height; y++) {
      for (let x = x0; x < x1; x++) {
        const px = (x - x0) * TILE, py = y * TILE;
        if (at(x, y) === 'R') {
          g.fillStyle = 'rgba(176,164,186,0.32)';
          if (!wall(x, y + 1)) g.fillRect(px, py + TILE - 2, TILE, 2);
          if (!wall(x, y - 1)) g.fillRect(px, py, TILE, 1);
          if (!wall(x - 1, y)) g.fillRect(px, py, 1, TILE);
          if (!wall(x + 1, y)) g.fillRect(px + TILE - 1, py, 1, TILE);
        } else if (y > 0 && at(x, y - 1) === 'R') {
          g.fillStyle = 'rgba(0,0,0,0.38)';
          g.fillRect(px, py, TILE, 4);
        }
      }
    }
  }

  /** Animated glints on one water tile (drawn per frame, screen space). */
  function drawWater(ctx, code, tx, ty, dx, dy, size, t) {
    const p = size / TILE;
    const deep = code === 'W', cave = code === 'u';
    const phase = hashAt(tx, ty, 7) * Math.PI * 2;
    const k = Math.sin(t / (deep || cave ? 1400 : 1000) + phase);
    if (k < 0.35) return;
    const a = (k - 0.35) / 0.65 * (deep ? 0.18 : cave ? 0.2 : 0.32);
    ctx.fillStyle = cave ? `rgba(150,226,222,${a.toFixed(3)})` : `rgba(158,214,240,${a.toFixed(3)})`;
    const ox = Math.floor(hashAt(tx, ty, 8) * 8) + 2;
    const oy = Math.floor(hashAt(tx, ty, 9) * 10) + 3;
    const drift = Math.round(Math.sin(t / 1700 + phase) * 1.5);
    ctx.fillRect(dx + (ox + drift) * p, dy + oy * p, 4 * p, p);
    ctx.fillRect(dx + (ox + drift + 2) * p, dy + (oy - 1) * p, 2 * p, p);
  }

  /* ---------------------------------------------------------------- objects */
  // own keys only, so a kind like "constructor" is just an unknown thing
  function knownObject(kind) { return Object.prototype.hasOwnProperty.call(OBJECTS, kind); }
  /** The name creatures read for a kind (from the world's data), else this sheet's, else the kind's id. */
  function objectName(kind) {
    const info = kindInfo(kind);
    if (info && info.name) return String(info.name);
    return knownObject(kind) ? OBJECTS[kind].name : String(kind || 'thing').replace(/_/g, ' ');
  }
  function terrainName(code) { return (TERRAIN[code] || { name: 'unknown ground' }).name; }

  /** A wishing stone's quiet light, shared by both skins: a pale halo on the ground under the
   *  stone (cx = tile centre, by = tile bottom), breathing slowly. Draw it before the sprite. */
  function drawWishAura(ctx, cx, by, size, t, seed) {
    const p = size / TILE;
    const k = 0.7 + 0.3 * Math.sin(t / 1100 + (seed % 628) / 100);
    const cy = by - 3 * p, r = 10 * p;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.translate(cx, cy);
    ctx.scale(1, 0.5);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r);
    g.addColorStop(0, `rgba(150,185,255,${(0.34 * k).toFixed(3)})`);
    g.addColorStop(0.55, `rgba(120,150,240,${(0.14 * k).toFixed(3)})`);
    g.addColorStop(1, 'rgba(120,150,240,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  /** Motes of pale light drifting up off a wishing stone, and now and then a twinkle above it.
   *  cx = centre of the sprite, top = its top edge. Draw it after the sprite. */
  function drawWishMotes(ctx, cx, top, size, t, seed) {
    const p = size / TILE;
    const q = Math.max(1, Math.round(p));
    for (let i = 0; i < 3; i++) {
      const cyc = t / 2300 + i / 3 + (seed % 97) / 97;
      const life = cyc % 1;
      const a = Math.sin(life * Math.PI) * 0.85;
      const x = cx + ((hash2(seed & 0xffff, i, Math.floor(cyc)) - 0.5) * 10 + Math.sin(life * 5 + i) * 1.2) * p;
      ctx.fillStyle = `rgba(224,236,255,${a.toFixed(3)})`;
      ctx.fillRect(Math.round(x), Math.round(top + (3 - life * 9) * p), q, q);
    }
    const tw = (t / 3100 + (seed % 53) / 53) % 1;
    if (tw < 0.22) {
      const a = Math.sin(tw / 0.22 * Math.PI);
      const x = Math.round(cx + ((seed % 7) - 3) * p), y = Math.round(top - 4 * p);
      ctx.fillStyle = `rgba(240,246,255,${(0.9 * a).toFixed(3)})`;
      ctx.fillRect(x, y, q, q);
      ctx.fillStyle = `rgba(190,215,255,${(0.6 * a).toFixed(3)})`;
      ctx.fillRect(x - q, y, q, q); ctx.fillRect(x + q, y, q, q);
      ctx.fillRect(x, y - q, q, q); ctx.fillRect(x, y + q, q, q);
    }
  }

  function drawObject(ctx, obj, dx, dy, size, t) {
    if (!knownObject(obj.kind)) return drawGlyph(ctx, kindGlyph(obj.kind, obj.id), dx, dy, size);  // no art: its glyph
    const spec = OBJECTS[obj.kind];
    const p = size / TILE;
    if (!ready) return drawObjectFallback(ctx, obj, spec, dx, dy, size, t);

    let cell = spec.s;
    if (spec.alt) {
      const v = hashStr(obj.id) % (spec.alt.length + 1);
      if (v > 0) cell = spec.alt[v - 1];
    }
    let tint = spec.tint || null;
    let flip = false;
    if (spec.fire) {
      if (obj.lit === false) tint = spec.unlitTint;
      else flip = Math.floor(t / 170 + hashStr(obj.id)) % 3 === 0;
    }
    if (spec.wish) drawWishAura(ctx, dx + size / 2, dy + size, size, t, hashStr(obj.id));
    blit(ctx, cell[0], cell[1], tint, dx, dy, size, flip);
    if (spec.wish) drawWishMotes(ctx, dx + size / 2, dy + 5 * p, size, t, hashStr(obj.id));

    if (spec.berries) {
      ctx.fillStyle = PAL.red;
      const spots = [[4, 5], [10, 4], [8, 9], [12, 9]];
      const n = 3 + (hashStr(obj.id) & 1);
      for (let i = 0; i < n; i++) ctx.fillRect(dx + spots[i][0] * p, dy + spots[i][1] * p, 2 * p, 2 * p);
    }
    if (spec.fleck) {
      ctx.fillStyle = spec.fleck;
      ctx.fillRect(dx + 5 * p, dy + 7 * p, p, p);
      ctx.fillRect(dx + 10 * p, dy + 9 * p, p, p);
      if (Math.sin(t / 600 + hashStr(obj.id)) > 0.7) ctx.fillRect(dx + 8 * p, dy + 5 * p, p, p);
    }
    if (spec.screen) {
      // blinking cursor on the terminal screen
      if (Math.floor(t / 530) % 2 === 0) {
        ctx.fillStyle = PAL.green;
        ctx.fillRect(dx + 6 * p, dy + 7 * p, 2 * p, p);
      }
    }
    if (spec.fire && obj.lit !== false) {
      // a few sparks drifting up
      for (let i = 0; i < 2; i++) {
        const life = ((t / 900) + i * 0.5 + hashAt(obj.x, obj.y, i)) % 1;
        ctx.fillStyle = rgba(PAL.gold, (1 - life).toFixed(2));
        const sx = 6 + i * 4 + Math.round(Math.sin(life * 6 + i) * 1.5);
        ctx.fillRect(dx + sx * p, dy + (3 - life * 6) * p, p, p);
      }
    }
  }

  function drawObjectFallback(ctx, obj, spec, dx, dy, size, t) {
    const p = size / TILE;
    const k = obj.kind;
    const R = (x, y, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(dx + x * p, dy + y * p, w * p, h * p); };
    const circle = (cx, cy, r, c) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(dx + cx * p, dy + cy * p, r * p, 0, Math.PI * 2); ctx.fill(); };
    switch (k) {
      case 'tree': R(7, 10, 2, 5, PAL.brown); circle(8, 7, 5.5, PAL.green); break;
      case 'pine': R(7, 12, 2, 3, PAL.brown); ctx.fillStyle = '#2cc56a'; ctx.beginPath(); ctx.moveTo(dx + 8 * p, dy + 1 * p); ctx.lineTo(dx + 14 * p, dy + 13 * p); ctx.lineTo(dx + 2 * p, dy + 13 * p); ctx.fill(); break;
      case 'stump': R(4, 8, 8, 6, PAL.brown); R(4, 7, 8, 2, '#d89a7a'); break;
      case 'bush': circle(8, 10, 5, PAL.green); R(5, 8, 2, 2, PAL.red); R(10, 9, 2, 2, PAL.red); break;
      case 'bush_empty': circle(8, 10, 5, '#3f7a52'); break;
      case 'rock': case 'copper_vein': case 'iron_vein':
        circle(8, 10, 5, spec.tint || PAL.bone);
        if (spec.fleck) { R(6, 9, 1, 1, spec.fleck); R(10, 11, 1, 1, spec.fleck); }
        break;
      case 'wishing_stone': {
        const seed = hashStr(obj.id);
        drawWishAura(ctx, dx + size / 2, dy + size, size, t, seed);
        circle(8, 10, 5, spec.tint);
        R(7, 8, 2, 2, '#eef4ff');
        drawWishMotes(ctx, dx + size / 2, dy + 5 * p, size, t, seed);
        break;
      }
      case 'clay': R(3, 9, 10, 5, '#c27a5c'); break;
      case 'campfire': {
        R(3, 12, 10, 2, PAL.brown);
        if (obj.lit !== false) { const f = Math.sin(t / 120) > 0 ? 1 : 0; circle(8, 9 - f, 3.5, PAL.red); circle(8, 9.5, 2, PAL.gold); }
        break;
      }
      case 'workbench': R(2, 6, 12, 3, PAL.brown); R(3, 9, 2, 5, PAL.brown); R(11, 9, 2, 5, PAL.brown); break;
      case 'furnace': R(3, 3, 10, 11, '#b8aa98'); R(6, 9, 4, 3, PAL.red); break;
      case 'wall': R(1, 2, 14, 12, PAL.brown); R(1, 7, 14, 1, PAL.rose); break;
      case 'sign': R(7, 8, 2, 7, PAL.brown); R(3, 3, 10, 6, PAL.brown); break;
      case 'chest': R(3, 6, 10, 8, PAL.brown); R(7, 9, 2, 2, PAL.gold); break;
      case 'terminal': R(3, 3, 10, 9, PAL.bone); R(5, 5, 6, 5, '#183a2a'); if (Math.floor(t / 530) % 2 === 0) R(6, 7, 2, 1, PAL.green); break;
      case 'tablet': R(4, 3, 8, 11, PAL.bone); R(6, 6, 4, 1, PAL.plum); R(6, 8, 4, 1, PAL.plum); break;
      case 'pile': circle(8, 11, 4, PAL.brown); break;
      default: drawGlyph(ctx, kindGlyph(k, obj.id), dx, dy, size);
    }
  }

  /* -------------------------------------------------------------- creatures */
  function creatureCell(id) { return CREATURES[hashStr(id) % CREATURES.length]; }

  /** opts: { dim:boolean, asleep:boolean, flip:boolean|undefined } */
  function drawCreature(ctx, cre, dx, dy, size, opts) {
    const o = opts || {};
    const base = cre.color || PAL.bone;
    const color = o.dim ? mix(base, '#5c5462', 0.55) : base;
    ctx.save();
    if (o.dim) ctx.globalAlpha = 0.72;
    if (o.asleep) ctx.globalAlpha *= 0.82;
    if (ready) {
      const [c, r] = creatureCell(cre.id);
      const flip = o.flip != null ? !!o.flip : !!((hashStr(cre.id) >> 4) & 1);
      blit(ctx, c, r, color, dx, dy, size, flip);
    } else {
      const p = size / TILE;
      ctx.fillStyle = color;
      ctx.fillRect(dx + 4 * p, dy + 7 * p, 8 * p, 7 * p);
      ctx.beginPath(); ctx.arc(dx + 8 * p, dy + 4.5 * p, 3 * p, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.35)';
      ctx.fillRect(dx + 6 * p, dy + 4 * p, p, p); ctx.fillRect(dx + 9 * p, dy + 4 * p, p, p);
    }
    ctx.restore();
  }

  /* ------------------------------------------------------------ text, icons */
  /** Draws pixel-font text from the sheet; returns the width drawn. */
  function drawGlyphText(ctx, text, x, y, scale, color) {
    const adv = 12 * scale, space = 7 * scale, size = TILE * scale;
    let cx = x;
    for (const ch of String(text)) {
      if (ch === ' ') { cx += space; continue; }
      const cell = glyphFor(ch);
      if (cell && ready) blit(ctx, cell[0], cell[1], color, Math.round(cx - 2 * scale), Math.round(y), size, false);
      cx += adv;
    }
    return cx - x;
  }
  function measureGlyphText(text, scale) {
    let w = 0;
    for (const ch of String(text)) w += ch === ' ' ? 7 * scale : 12 * scale;
    return w;
  }

  /** Builds data-URL masks for every UI icon and exposes them as CSS variables. */
  function installIconStyles(root, dpr) {
    if (!ready) return false;
    const scale = Math.max(1, Math.ceil(dpr || 1));
    for (const [name, [c, r]] of Object.entries(ICONS)) {
      const cv = document.createElement('canvas');
      cv.width = TILE * scale; cv.height = TILE * scale;
      const g = cv.getContext('2d');
      g.imageSmoothingEnabled = false;
      blit(g, c, r, '#ffffff', 0, 0, TILE * scale, false);
      root.style.setProperty('--ico-' + name, `url(${cv.toDataURL()})`);
    }
    root.classList.add('sprites-ok');
    return true;
  }

  /** A small canvas showing a creature sprite, for the side panel. */
  function creatureBadge(cre, px) {
    const dpr = window.devicePixelRatio || 1;
    const cv = document.createElement('canvas');
    cv.width = Math.round(px * dpr); cv.height = Math.round(px * dpr);
    cv.style.width = px + 'px'; cv.style.height = px + 'px';
    const g = cv.getContext('2d');
    g.imageSmoothingEnabled = false;
    drawCreature(g, cre, 0, 0, cv.width, {});
    return cv;
  }

  /** A 16x16 canvas with one (optionally tinted) glyph, or null before the sheet loads. */
  function glyphCanvas(c, r, tint) {
    if (!ready) return null;
    const cv = document.createElement('canvas');
    cv.width = TILE; cv.height = TILE;
    const g = cv.getContext('2d');
    blit(g, c, r, tint || null, 0, 0, TILE, false);
    return cv;
  }

  /* ---------------------------------------------------------------- roofs (see roofs.js)
   * A drawn roof for a building's rectangle: shingle rows, a lit and a shaded slope split by a ridge along the longer
   * side, a dark rim and eave. Painted once per design and size at 1 px per art pixel, then scaled by drawImage. */
  const ROOF_COLORS = { tent: '#cdb586', hut: '#b5543a', storehouse: '#8a6240', workshop: '#566f8c' };
  const roofColor = (design) => ROOF_COLORS[design] || '#8a6a58';
  const roofCache = new Map();

  function paintRoof(g, W, H, color) {
    const rim = '#2b2230', dark = mix(color, '#120e18', 0.38), mid = mix(color, '#120e18', 0.16), light = mix(color, '#ffffff', 0.24);
    const horiz = W >= H, L = horiz ? W : H, S = horiz ? H : W;
    const r = (a, b, c, d) => (horiz ? g.fillRect(a, b, c, d) : g.fillRect(b, a, d, c));   // (along, across, length, thickness)
    g.fillStyle = rim; g.fillRect(0, 0, W, H);
    const ridge = Math.floor(S / 2);
    g.fillStyle = light; r(1, 1, L - 2, ridge - 1);               // the sunny slope
    g.fillStyle = mid; r(1, ridge + 1, L - 2, S - ridge - 2);     // the shaded slope
    for (let c = 1; c < S - 1; c += 4) {                           // shingle rows
      g.fillStyle = dark;
      r(1, c, L - 2, 1);
      for (let a = 1 + ((c >> 2) % 2) * 4; a < L - 1; a += 8) r(a, c + 1, 1, 3);
    }
    g.fillStyle = light; r(1, ridge - 1, L - 2, 2);               // the ridge
    g.fillStyle = dark; r(1, ridge + 1, L - 2, 1);
    g.fillStyle = dark; g.fillRect(1, H - 3, W - 2, 2);          // the south eave
  }

  /** Draws the roof of building b into the pixel rectangle (x, y, w, h); ts = pixels per tile. */
  function drawRoof(ctx, b, x, y, w, h, ts) {
    const W = (b.x1 - b.x0 + 1) * TILE, H = (b.y1 - b.y0 + 1) * TILE, key = b.design + '|' + W + '|' + H;
    let cv = roofCache.get(key);
    if (!cv) {
      if (roofCache.size > 48) roofCache.clear();
      cv = document.createElement('canvas');
      cv.width = W; cv.height = H;
      paintRoof(cv.getContext('2d'), W, H, roofColor(b.design));
      roofCache.set(key, cv);
    }
    ctx.drawImage(cv, Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  window.SwarmTiles = {
    glyphCanvas,
    name: 'kenney', credit: 'Art: Kenney 1-Bit Pack (CC0)',
    spriteTopTiles: 1, drawsWater: true, iconStyle: () => null, hasObject: knownObject,
    TILE, SHEET_SRC, PAL, TERRAIN, OBJECTS, CREATURES, ICONS, GLYPHS, MONO,
    setKinds, kindInfo, kindGlyph, glyphSprite, drawGlyph, kenneyLook,
    load, get ready() { return ready; },
    hash2, hashAt, setOrigin, origin, hashStr, rgb, mix, rgba, readable,
    renderTerrain, drawWater, isWater, drawWallEdges,
    drawObject, objectName, terrainName, drawWishAura, drawWishMotes,
    drawCreature, creatureBadge, drawRoof, roofColor,
    drawGlyphText, measureGlyphText, installIconStyles,
  };
})();
