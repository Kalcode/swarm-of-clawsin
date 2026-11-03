/* Swarm World almanac: everything in the game, what this world's creatures have found, a census, and what's coming.
 *
 * Reads GET /api/almanac (swarmworld/server/almanac.py) every 30 s, keeping the view as it was: the tree's pan and
 * zoom, the open card, filters, scroll positions and open sections. Items and kinds are drawn with the viewer's
 * skins (tiles.js, limezu.js, ascii.js), in whichever art the viewer last used, so the almanac matches the map.
 * The endpoint answers on the world's own machine; elsewhere add ?token=<join token> to this page's address.
 * Everything here is for the user; creatures never see it.
 */
(function () {
  'use strict';

  const T = window.SwarmTiles;
  const SKINS = { limezu: () => window.SwarmLimeZu, kenney: () => T, ascii: () => window.SwarmASCII };
  const SKIN_LABEL = { limezu: 'LimeZu', kenney: 'Kenney', ascii: 'ASCII' };
  const SKIN_KEY = 'swarmworld.skin';
  const REFRESH_MS = 30000;
  const DAY_TICKS = 1200;
  const TABS = ['tree', 'things', 'verbs', 'census', 'packs', 'roadmap'];
  const params = new URLSearchParams(location.search);
  const TOKEN = params.get('token') || '';
  const NARROW = window.matchMedia('(max-width: 720px)');

  const $ = (id) => document.getElementById(id);
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const fmt = (n) => Number(n || 0).toLocaleString('en-US');
  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : (many || one + 's')}`;
  const md = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>');
  const cap = (s) => String(s || '').charAt(0).toUpperCase() + String(s || '').slice(1);
  const dayOf = (tick) => Math.floor(tick / DAY_TICKS) + 1;
  const TILE_WORDS = { g: 'grass', d: 'dirt', s: 'sand', w: 'shallow water', W: 'deep water', r: 'rocky ground', f: 'forest floor' };

  /* ------------------------------------------------------------------ state */
  const S = {
    X: null,                    // the indexed almanac
    tab: 'tree',
    sel: null,                  // the tree node whose card is open
    hover: null,
    view: NARROW.matches ? 'list' : 'graph',
    q: '',
    status: new Set(['raw', 'start', 'found', 'unfound']),
    packs: null,                // Set of packs shown; null until the first load
    tf: null,                   // tree transform { x, y, k }
    layout: null,               // { sig, pos: Map id -> {x, y}, W, H, tiers }
    thingsQ: '', thingsGroups: null,
    verbSort: 'schema',
    itemsTable: false,
    open: new Set(['rm-progress', 'rm-open']),
    fetchedAt: 0, lastOk: 0, error: null, loading: false,
    dirty: new Set(TABS),
  };
  let SK = T;

  /* ------------------------------------------------------------------ data */
  function index(d) {
    const X = { d };
    X.items = new Map(d.items.map((i) => [i.id, i]));
    X.recipes = new Map(d.recipes.map((r) => [r.output, r]));
    X.procs = new Map();
    for (const p of d.processes) (X.procs.get(p.output) || X.procs.set(p.output, []).get(p.output)).push(p);
    X.designs = new Map(d.designs.map((x) => ['design:' + x.id, x]));
    X.kinds = new Map(d.kinds.map((k) => [k.id, k]));
    X.packs = new Map(d.packs.map((p) => [p.id, p]));
    X.inventions = new Set(d.inventions.map((i) => i.id));
    X.creatures = d.world.creatures;
    X.modelColor = new Map();
    for (const c of X.creatures) if (!X.modelColor.has(c.model)) X.modelColor.set(c.model, c.color);
    X.knownBy = new Map();
    for (const c of X.creatures) for (const r of c.known) (X.knownBy.get(r) || X.knownBy.set(r, []).get(r)).push(c);
    X.preds = new Map(); X.succs = new Map();
    for (const e of d.tree.edges) {
      if (e.back) continue;
      (X.preds.get(e.to) || X.preds.set(e.to, []).get(e.to)).push(e.from);
      (X.succs.get(e.from) || X.succs.set(e.from, []).get(e.from)).push(e.to);
    }
    X.nodes = new Map(d.tree.nodes.map((n) => [n.id, n]));
    return X;
  }
  const nameOf = (id) => {
    const X = S.X;
    if (X && X.items.has(id)) return X.items.get(id).name;
    if (X && X.designs.has(id)) return X.designs.get(id).name;
    if (X && X.kinds.has(id)) return X.kinds.get(id).name;
    return String(id || '').replace(/^design:/, '').replace(/_/g, ' ');
  };
  const kindName = (k) => (S.X && S.X.kinds.has(k) ? S.X.kinds.get(k).name : String(k).replace(/_/g, ' '));
  function statusOf(id) {
    const X = S.X;
    if (X.designs.has(id)) return X.designs.get(id).status;
    return (X.items.get(id) || {}).status || 'raw';
  }
  const STATUS_LABEL = {
    raw: 'Gathered, no recipe', start: 'Known at start', found: 'Discovered here', invented: 'Invented here',
    unfound: 'Not found yet', built: 'Built here', site: 'Being built', unbuilt: 'Not built yet',
  };
  const STATUS_SHORT = {
    raw: 'gathered', start: 'at start', found: 'discovered', invented: 'invented', unfound: 'not found',
    built: 'built', site: 'being built', unbuilt: 'not built',
  };
  const GROUP_OF = { raw: 'raw', start: 'start', found: 'found', invented: 'found', built: 'found', site: 'found', unfound: 'unfound', unbuilt: 'unfound' };
  const STATUS_CHIPS = [
    ['raw', 'Gathered'], ['start', 'Known at start'], ['found', 'Discovered here'], ['unfound', 'Not found yet'],
  ];
  const packOf = (id) => (S.X.designs.has(id) ? S.X.designs.get(id).pack : (S.X.items.get(id) || {}).pack);

  /* ------------------------------------------------------------------ skins and icons */
  const iconCache = new Map();
  const lookCache = new Map();
  const ITEM_GLYPH = [  // a roguelike class glyph for items that aren't kinds: the first tag that matches
    ['invention', '✦', '#ffd75e'], ['drink', '!', '#7cc6f2'], ['container', 'u', '#c97c5e'], ['weapon', ')', '#cfc6b8'],
    ['pickaxe', '(', '#d0874e'], ['axe', '(', '#cfc6b8'], ['tool', '(', '#cfc6b8'], ['instrument', '♪', '#e9cf9c'],
    ['gift', '♥', '#ff8fb1'], ['writable', '?', '#efe6d2'], ['station', '&', '#ffb347'], ['storage', '≡', '#c98a4e'],
    ['building', '#', '#bf7958'], ['metal', '=', '#aab4c4'], ['ore', '$', '#d0874e'], ['fuel', '•', '#8a8490'],
    ['fish', '%', '#9ab8d8'], ['meat', '%', '#e0707a'], ['preserved', '%', '#c99a5e'], ['food_part', '%', '#e9cf9c'],
    ['food', '%', '#e8945c'], ['seed', ',', '#b8d86a'], ['crop', 'ψ', '#e8c25a'], ['plant', '"', '#7fdc6e'],
    ['wood', '=', '#bf7958'], ['stone', '*', '#a39ca6'], ['earth', ':', '#c97c5e'], ['tool_part', '~', '#d2b48c'],
    ['material', '~', '#cfc6b8'],
  ];
  function glyphOf(id) {
    const X = S.X;
    if (X && X.kinds.has(id)) return T.kindGlyph(id);
    const tags = (X && X.items.get(id) && X.items.get(id).tags) || [];
    for (const [tag, char, color] of ITEM_GLYPH) if (tags.includes(tag)) return { char, color };
    return { char: [...nameOf(id)][0] || '¤', color: '#b9aebb' };
  }

  /** A kind drawn by the current skin, trimmed to what was drawn: a data URL, or null when it draws nothing. */
  function kindLook(kind) {
    const key = SK.name + '|' + kind;
    if (lookCache.has(key)) return lookCache.get(key);
    let url = null;
    try {
      const ts = 32;
      const cv = document.createElement('canvas');
      cv.width = ts * 3; cv.height = ts * 3;
      const g = cv.getContext('2d');
      g.imageSmoothingEnabled = false;
      const obj = { id: 'almanac-' + kind, kind, x: 0, y: 0, lit: true, stage: 2, crop: 'wheat', label: kindName(kind), text: '' };
      SK.drawObject(g, obj, ts, ts * 2, ts, 0, { dir: 'down', moving: false });
      url = trimmed(cv);
    } catch (err) { url = null; }
    lookCache.set(key, url);
    return url;
  }
  function trimmed(cv) {
    const { width: w, height: h } = cv;
    const px = cv.getContext('2d').getImageData(0, 0, w, h).data;
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (px[(y * w + x) * 4 + 3] > 10) {
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (y < y0) y0 = y; if (y > y1) y1 = y;
        }
      }
    }
    if (x1 < 0) return null;
    const side = Math.max(x1 - x0 + 1, y1 - y0 + 1) + 2;
    const out = document.createElement('canvas');
    out.width = side; out.height = side;
    out.getContext('2d').drawImage(cv, x0, y0, x1 - x0 + 1, y1 - y0 + 1,
      Math.floor((side - (x1 - x0 + 1)) / 2), side - 1 - (y1 - y0 + 1), x1 - x0 + 1, y1 - y0 + 1);
    return out.toDataURL();
  }
  const hasArt = (kind) => SK.name !== 'ascii' && (!SK.hasObject || SK.hasObject(kind));

  function glyphHTML(g, px, box) {
    return `<span class="ic glyph${box ? ' box' : ''}" style="--px:${px}px;--g:${esc(g.color)}" aria-hidden="true">${esc(g.char)}</span>`;
  }
  /** An item's icon: the LimeZu icon when that skin is on, else the kind's own art, else its glyph. */
  function icon(id, px) {
    px = px || 20;
    const key = SK.name + '|' + id + '|' + px;
    if (iconCache.has(key)) return iconCache.get(key);
    const X = S.X;
    let html = null;
    if (id.startsWith('design:')) {
      const d = X.designs.get(id);
      const k = d && (d.kinds.includes(d.id) ? d.id : d.id === 'bridge' ? 'bridge' : null);
      const url = k && hasArt(k) ? kindLook(k) : null;
      html = url ? `<span class="ic" style="--px:${px}px" aria-hidden="true"><img alt="" src="${url}"></span>`
        : glyphHTML({ char: d && d.over_water ? '=' : '⌂', color: T.roofColor ? T.roofColor(d ? d.id : '') : '#c8a882' }, px);
    } else {
      if (SK.name === 'limezu' && SK.iconStyle) {
        const st = SK.iconStyle(id, px) || (X.inventions.has(id) ? SK.iconStyle('_invention', px) : null);
        if (st) html = `<span class="ic" style="--px:${px}px;${esc(st)}" aria-hidden="true"></span>`;
      }
      if (!html && X.kinds.has(id) && hasArt(id)) {
        const url = kindLook(id);
        if (url) html = `<span class="ic" style="--px:${px}px" aria-hidden="true"><img alt="" src="${url}"></span>`;
      }
      if (!html) html = glyphHTML(glyphOf(id), px);
    }
    iconCache.set(key, html);
    return html;
  }
  /** A kind's look for the Things table: its art at the size it has on the map, or its glyph. */
  function lookHTML(kind) {
    const url = hasArt(kind) ? kindLook(kind) : null;
    return url ? `<img alt="" src="${url}">` : glyphHTML(T.kindGlyph(kind), 30, SK.name === 'ascii');
  }
  const itemChip = (id, n, extra) =>
    `<button type="button" class="alm-item${extra ? ' ' + extra : ''}" data-go="${esc(id)}" title="${esc(nameOf(id))}">` +
    `${icon(id, 20)}<span>${esc(nameOf(id))}</span>${id.startsWith('design:') ? '<span class="n">build</span>' : ''}` +
    `${n && n > 1 ? `<span class="n">×${fmt(n)}</span>` : ''}</button>`;

  async function setSkin(name, remember) {
    const sk = SKINS[name] && SKINS[name]();
    if (!sk) return false;
    if (sk !== T && sk.load && !sk.ready) {
      const ok = await sk.load();
      if (!ok) return false;
    }
    SK = sk;
    if (remember) { try { localStorage.setItem(SKIN_KEY, name); } catch (e) { /* private mode */ } }
    document.body.dataset.skin = SK.name;
    iconCache.clear();
    renderSkinSwitch();
    for (const t of TABS) S.dirty.add(t);
    if (S.X) render();
    return true;
  }
  function renderSkinSwitch() {
    const lz = window.SwarmLimeZu;
    const opts = Object.keys(SKINS).filter((k) => k !== 'limezu' || (lz && lz.ready));
    $('skin-switch').innerHTML = opts.map((k) =>
      `<button type="button" role="radio" data-skin="${k}" aria-checked="${SK.name === k}">${SKIN_LABEL[k]}</button>`).join('');
  }

  function drawTitle() {
    const cv = $('alm-title');
    if (!T.ready) { cv.removeAttribute('width'); return; }
    const d = window.devicePixelRatio || 1;
    const fire = 16, text = 'SWARM WORLD';
    const w = Math.ceil(fire + 8 + T.measureGlyphText(text, 1)), h = 16;
    cv.width = Math.round(w * d); cv.height = Math.round(h * d);
    cv.style.width = w + 'px'; cv.style.height = h + 'px';
    const g = cv.getContext('2d');
    g.setTransform(d, 0, 0, d, 0, 0);
    g.imageSmoothingEnabled = false;
    T.drawObject(g, { id: 'title', kind: 'campfire', x: 0, y: 0, lit: true }, 0, 0, fire, 0);
    T.drawGlyphText(g, text, fire + 8, 0, 1, '#ebe3d5');
  }

  /* ------------------------------------------------------------------ fetching */
  async function load(manual) {
    if (S.loading) return;
    S.loading = true;
    setSync('loading', manual ? 'Refreshing' : (S.X ? 'Refreshing' : 'Loading'));
    try {
      const r = await fetch('api/almanac', { cache: 'no-store', headers: TOKEN ? { 'X-Swarm-Token': TOKEN } : {} });
      if (r.status === 403) throw Object.assign(new Error('forbidden'), { forbidden: true });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const prev = S.X;
      S.X = index(d);
      S.error = null;
      S.lastOk = Date.now();
      if (T.setKinds) T.setKinds(Object.fromEntries(d.kinds.map((k) => [k.id, { name: k.name, look: k.look, glyph: k.glyph, glow: k.glow }])));
      if (window.SwarmLimeZu && window.SwarmLimeZu.setInventions) window.SwarmLimeZu.setInventions(d.inventions);
      iconCache.clear();
      if (!prev) {
        S.packs = new Set(d.packs.map((p) => p.id));
        S.thingsGroups = new Set(Object.keys(d.world.groups));
      } else {
        for (const p of d.packs) if (!prev.packs.has(p.id)) S.packs.add(p.id);  // a pack new since the last read shows
      }
      for (const t of TABS) S.dirty.add(t);
      $('alm-veil').classList.add('is-done');
      render();
      setSync('live', 'Live');
    } catch (err) {
      S.error = err;
      if (!S.X) {
        $('veil-title').textContent = err.forbidden ? 'The almanac opens on the world\'s own machine' : 'Couldn\'t reach the world';
        $('veil-sub').innerHTML = err.forbidden
          ? 'It lists the backlog and everything in the game, so from elsewhere it needs the join token: add <code>?token=…</code> to this page\'s address.'
          : `The server didn't answer (${esc(err.message)}). It tries again every 30 seconds.`;
      }
      setSync('offline', err.forbidden ? 'Needs the token' : 'Offline');
    } finally {
      S.loading = false;
      S.fetchedAt = Date.now();
      renderClock();
    }
  }
  function setSync(state, label) {
    $('alm-sync').dataset.state = state;
    $('alm-sync-label').textContent = label;
  }
  function renderClock() {
    const X = S.X;
    if (!X) return;
    const w = X.d.world, c = w.clock || {};
    const ago = S.lastOk ? Math.round((Date.now() - S.lastOk) / 1000) : 0;
    const awake = X.creatures.filter((x) => !x.asleep).length;
    $('alm-clock').innerHTML = `<b>Day ${fmt(X.d.day)}</b> · ${esc(c.phase || '')} · tick <span class="num">${fmt(X.d.tick)}</span>` +
      ` · ${plural(X.creatures.length, 'creature')} (${fmt(awake)} awake)` +
      (S.error ? ` · <span title="${esc(S.error.message)}">showing the last answer, ${fmt(ago)} s old</span>` : ` · updated ${ago < 5 ? 'just now' : fmt(ago) + ' s ago'}`);
    $('alm-sync').title = S.lastOk ? `Last read ${new Date(S.lastOk).toLocaleTimeString()}; every 30 s` : '';
  }

  /* ------------------------------------------------------------------ routing and tabs */
  function readHash() {
    const [tab, rest] = decodeURIComponent(location.hash.replace(/^#/, '')).split('/');
    if (TABS.includes(tab)) S.tab = tab;
    if (tab === 'tree' && rest) S.sel = rest.startsWith('design-') ? 'design:' + rest.slice(7) : rest;
  }
  function writeHash() {
    const sel = S.tab === 'tree' && S.sel ? '/' + S.sel.replace(/^design:/, 'design-') : '';
    history.replaceState(null, '', '#' + S.tab + sel + '');
  }
  function setTab(tab, focus) {
    if (!TABS.includes(tab)) return;
    S.tab = tab;
    for (const t of TABS) {
      $('tab-' + t).setAttribute('aria-selected', String(t === tab));
      $('tab-' + t).tabIndex = t === tab ? 0 : -1;
      $('pane-' + t).hidden = t !== tab;
    }
    if (focus) $('tab-' + tab).focus();
    writeHash();
    render();
  }
  function renderCounts() {
    const d = S.X.d;
    $('n-tree').textContent = d.recipes.length;
    $('n-things').textContent = d.kinds.length;
    $('n-verbs').textContent = d.verbs.length;
    $('n-packs').textContent = d.packs.length;
    const open = (d.roadmap.counts.open || 0) + (d.roadmap.counts.progress || 0);
    $('n-roadmap').textContent = open || '';
  }
  function render() {
    if (!S.X) return;
    renderCounts();
    const pane = $('pane-' + S.tab);
    if (!S.dirty.has(S.tab)) return;
    S.dirty.delete(S.tab);
    const top = pane.scrollTop;
    ({ tree: renderTree, things: renderThings, verbs: renderVerbs, census: renderCensus, packs: renderPacks, roadmap: renderRoadmap })[S.tab]();
    pane.scrollTop = top;
  }

  /* ------------------------------------------------------------------ tech tree: layout */
  const NODE_W = 168, NODE_H = 30, COL_W = 168 + 78, ROW_H = 38, TOP = 44;

  function layout() {
    const X = S.X;
    const nodes = X.d.tree.nodes;
    const sig = nodes.map((n) => n.id + ':' + n.tier).join(',') + '|' + X.d.tree.edges.length;
    if (S.layout && S.layout.sig === sig) return S.layout;
    const maxTier = Math.max(0, ...nodes.map((n) => n.tier));
    const cols = Array.from({ length: maxTier + 1 }, () => []);
    for (const n of nodes) cols[n.tier].push(n.id);
    const rank = { raw: 0, start: 1, found: 2, invented: 2, unfound: 3, built: 2, site: 2, unbuilt: 3 };
    for (const col of cols) col.sort((a, b) => (packOf(a) || '').localeCompare(packOf(b) || '') ||
      (rank[statusOf(a)] - rank[statusOf(b)]) || nameOf(a).localeCompare(nameOf(b)));
    const y = new Map();
    const pack = () => cols.forEach((col) => col.forEach((id, i) => y.set(id, i)));
    pack();
    const bary = (id, map) => {
      const xs = (map.get(id) || []).filter((o) => y.has(o)).map((o) => y.get(o));
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
    };
    const sortBy = (col, map) => {
      const keyed = col.map((id, i) => [id, bary(id, map) ?? i]);
      keyed.sort((a, b) => a[1] - b[1]);
      col.splice(0, col.length, ...keyed.map((k) => k[0]));
    };
    for (let it = 0; it < 6; it++) {
      for (let t = 1; t <= maxTier; t++) { sortBy(cols[t], X.preds); pack(); }
      for (let t = maxTier - 1; t >= 0; t--) { sortBy(cols[t], X.succs); pack(); }
    }
    const tallest = Math.max(...cols.map((c) => c.length));
    const pos = new Map();
    cols.forEach((col, t) => {
      const off = ((tallest - col.length) * ROW_H) / 2;
      col.forEach((id, i) => pos.set(id, { x: t * COL_W, y: TOP + off + i * ROW_H }));
    });
    S.layout = { sig, pos, cols, W: (maxTier + 1) * COL_W - (COL_W - NODE_W), H: TOP + tallest * ROW_H };
    return S.layout;
  }

  /* ------------------------------------------------------------------ tech tree: filters and focus */
  function matches(id) {
    const X = S.X;
    if (!S.packs.has(packOf(id))) return false;
    if (!S.status.has(GROUP_OF[statusOf(id)])) return false;
    return !S.q || searchHit(id);
  }
  function searchHit(id) {
    if (!S.q) return false;
    const q = S.q;
    const it = S.X.items.get(id) || S.X.designs.get(id) || {};
    return nameOf(id).toLowerCase().includes(q) || id.includes(q.replace(/\s+/g, '_')) ||
      (it.aliases || []).some((a) => a.toLowerCase().includes(q));
  }
  /** What to light up around a node: for the open card, everything it takes to make it and what it's used in;
   *  while hovering, its direct neighbours. */
  function nearOf(id, deep) {
    const X = S.X;
    const up = new Set([id]);
    const stack = [id];
    while (stack.length) {
      const n = stack.pop();
      for (const p of X.preds.get(n) || []) {
        if (!up.has(p)) { up.add(p); if (deep) stack.push(p); }
      }
    }
    const down = new Set(X.succs.get(id) || []);
    return { up, down };
  }

  /* ------------------------------------------------------------------ tech tree: render */
  function renderTree() {
    renderTreeBar();
    const graph = S.view === 'graph';
    $('tt-viewport').hidden = !graph;
    $('tt-list').hidden = graph;
    if (graph) renderGraph(); else renderList();
    renderCard();
  }
  function renderTreeBar() {
    const X = S.X;
    const ids = [...X.nodes.keys()];
    const counts = {};
    for (const id of ids) counts[GROUP_OF[statusOf(id)]] = (counts[GROUP_OF[statusOf(id)]] || 0) + 1;
    $('tt-status').innerHTML = STATUS_CHIPS.map(([k, label]) =>
      `<button type="button" class="alm-chip st-${k}" data-status="${k}" aria-pressed="${S.status.has(k)}">` +
      `<span class="st-mark" aria-hidden="true"></span>${esc(label)}<span class="n">${fmt(counts[k] || 0)}</span></button>`).join('');
    const packCounts = {};
    for (const id of ids) packCounts[packOf(id)] = (packCounts[packOf(id)] || 0) + 1;
    $('tt-packs').innerHTML = X.d.packs.filter((p) => packCounts[p.id]).map((p) =>
      `<button type="button" class="alm-chip" data-pack="${esc(p.id)}" aria-pressed="${S.packs.has(p.id)}">${esc(p.id)}<span class="n">${fmt(packCounts[p.id])}</span></button>`).join('');
    for (const b of $('tt-view').querySelectorAll('[data-view]')) b.setAttribute('aria-checked', String(b.dataset.view === S.view));
  }

  function edgePath(a, b) {
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
    if (x2 > x1) {
      const dx = Math.max(28, (x2 - x1) * 0.5);
      return `M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
    }
    return `M${x1} ${y1}C${x1 + 70} ${y1 - 40} ${x2 - 70} ${y2 - 40} ${x2} ${y2}`;
  }

  function renderGraph() {
    const X = S.X;
    const L = layout();
    const world = $('tt-world');
    world.style.width = L.W + 'px'; world.style.height = L.H + 'px';
    const tierName = (t) => (t === 0 ? 'gathered by hand' : t === L.cols.length - 1 ? 'the far end' : '');
    let html = L.cols.map((col, t) =>
      `<div class="tt-col" style="left:${t * COL_W}px"><b>Tier ${t}</b>${tierName(t) ? ' · ' + tierName(t) : ''} · ${col.length}</div>` +
      `<div class="tt-col-rule" style="left:${t * COL_W}px;width:${NODE_W}px"></div>`).join('');
    html += `<svg class="tt-edges" id="tt-edges" width="${L.W}" height="${L.H}" viewBox="0 0 ${L.W} ${L.H}" aria-hidden="true">`;
    for (const e of X.d.tree.edges) {
      const a = L.pos.get(e.from), b = L.pos.get(e.to);
      if (!a || !b) continue;
      html += `<path class="e-${e.kind}${e.back ? ' back' : ''}" data-from="${esc(e.from)}" data-to="${esc(e.to)}" d="${edgePath(a, b)}"/>`;
    }
    html += '</svg>';
    for (const [id, p] of L.pos) {
      const st = statusOf(id);
      const design = id.startsWith('design:');
      html += `<button type="button" class="tn st-${st}${design ? ' design' : ''}" data-id="${esc(id)}" style="left:${p.x}px;top:${p.y}px"` +
        ` aria-label="${esc(nameOf(id))}${design ? ' (a building)' : ''}: ${esc(STATUS_LABEL[st])}" title="${esc(nameOf(id))}${design ? ' (a building)' : ''} · ${esc(STATUS_LABEL[st])}">` +
        `${icon(id, 20)}<span class="nm">${esc(nameOf(id))}</span>${design ? '<span class="tg">build</span>' : ''}` +
        '<span class="st-mark" aria-hidden="true"></span></button>';
    }
    world.innerHTML = html;
    if (!S.tf) fit(false, true);
    applyTf();
    paintFocus();
    if (S.sel && S.pendingCenter) { S.pendingCenter = false; centerOn(S.sel, false); }
  }

  function paintFocus() {
    const X = S.X;
    if (!X || S.tab !== 'tree') return;
    const focusId = S.hover || S.sel;
    const near = focusId ? nearOf(focusId, focusId === S.sel && !S.hover) : null;
    if (S.view === 'graph') {
      const world = $('tt-world');
      world.classList.toggle('has-focus', !!near);
      for (const el of world.querySelectorAll('.tn')) {
        const id = el.dataset.id;
        el.classList.toggle('is-dim', !matches(id));
        el.classList.toggle('is-match', searchHit(id));
        el.classList.toggle('is-sel', id === S.sel);
        el.classList.toggle('is-near', !!near && (near.up.has(id) || near.down.has(id)));
      }
      const svg = $('tt-edges');
      if (!svg) return;
      svg.classList.toggle('has-focus', !!near);
      for (const p of svg.querySelectorAll('path')) {
        const f = p.dataset.from, t = p.dataset.to;
        const hl = !!near && ((near.up.has(f) && near.up.has(t)) || (f === focusId && near.down.has(t)));
        p.classList.toggle('hl', hl);
        p.classList.toggle('dim', !near && (!matches(f) || !matches(t)));
      }
    } else {
      for (const el of $('tt-list').querySelectorAll('.tt-row')) {
        el.classList.toggle('is-dim', !matches(el.dataset.id));
        el.classList.toggle('is-sel', el.dataset.id === S.sel);
      }
    }
  }

  function howLine(id) {
    const X = S.X;
    if (id.startsWith('design:')) {
      const d = X.designs.get(id);
      return 'build: ' + Object.entries(d.needs).map(([i, n]) => `${n} ${nameOf(i)}`).join(', ');
    }
    const r = X.recipes.get(id);
    if (r) {
      let s = Object.entries(r.inputs).map(([i, n]) => (n > 1 ? `${n} ${nameOf(i)}` : nameOf(i))).join(' + ');
      if (r.tools.length) s += ', holding ' + r.tools.map(nameOf).join(', ');
      if (r.station) s += ', at a ' + nameOf(r.station);
      return s;
    }
    const it = X.items.get(id);
    const procs = X.procs.get(id) || [];
    if (procs.length) return procs.map((p) => `${p.how} ${Object.keys(p.inputs).map(nameOf).join(', ')}`).join('; ');
    const src = (it && it.sources) || [];
    if (src.length) return [...new Set(src.map(sourceShort))].join(' · ');
    return (it && it.hint) || '';
  }
  function sourceShort(s) {
    const where = s.how === 'ground' || s.how === 'fish' ? s.source : kindName(s.source);
    const verb = { gather: 'from', hunt: 'hunt', fish: 'fish in', ground: 'from', animal: 'from', harvest: 'harvest' }[s.how] || s.how;
    return `${verb} ${where}${s.tools.length ? ' (' + s.tools.map(nameOf).join(' or ') + ')' : ''}`;
  }

  function renderList() {
    const X = S.X;
    const L = layout();
    let html = '';
    L.cols.forEach((col, t) => {
      const ids = [...col].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
      html += `<section class="tt-tier"><h3>Tier ${t}<small>${t === 0 ? 'gathered by hand · ' : ''}${plural(ids.length, 'thing')}</small></h3><ul class="tt-rows">`;
      for (const id of ids) {
        const st = statusOf(id);
        html += `<li><button type="button" class="tt-row st-${st}" data-id="${esc(id)}">${icon(id, 22)}` +
          `<span class="nm">${esc(nameOf(id))}${id.startsWith('design:') ? '<span class="tg">building</span>' : ''}</span>` +
          `<span class="st st-${st}"><span class="st-mark" aria-hidden="true"></span>${esc(STATUS_SHORT[st])}</span>` +
          `<span class="how">${esc(howLine(id))}</span></button></li>`;
      }
      html += '</ul></section>';
    });
    const top = $('tt-list').scrollTop;
    $('tt-list').innerHTML = html;
    $('tt-list').scrollTop = top;
    paintFocus();
  }

  /* ------------------------------------------------------------------ tech tree: the card */
  function renderCard() {
    const card = $('tt-card');
    const X = S.X;
    const id = S.sel;
    if (!id || !(X.items.has(id) || X.designs.has(id))) { card.hidden = true; card.innerHTML = ''; return; }
    card.hidden = false;
    const top = card.scrollTop;
    card.innerHTML = id.startsWith('design:') ? designCard(id) : itemCard(id);
    card.scrollTop = top;
  }
  const head = (id, sub) =>
    `<div class="cd-sheet-grip" aria-hidden="true"></div><div class="cd-head">${icon(id, 32)}` +
    `<div><h2 class="cd-name">${esc(nameOf(id))}</h2><p class="cd-id">${sub}</p></div>` +
    `<button type="button" class="alm-btn icon cd-close" data-close aria-label="Close" title="Close (Esc)">×</button></div>`;
  const who = (name, id, model) => {
    const c = S.X.creatures.find((x) => x.id === id);
    return `<b>${esc(name || 'someone')}</b>${model ? ` (${esc(model)})` : ''}${c ? '' : ' <span class="t-sub">(no longer here)</span>'}`;
  };
  function itemCard(id) {
    const X = S.X;
    const it = X.items.get(id);
    const r = X.recipes.get(id);
    const st = it.status;
    const d = it.discovered;
    let status;
    if (st === 'found' || st === 'invented') {
      status = `${st === 'invented' ? 'Invented' : 'Discovered'} by ${who(d.by, d.by_id, d.model)} on day ${fmt(d.day)}, tick ${fmt(d.tick)}.`;
    } else if (st === 'start') {
      status = '<b>Known at start.</b> Every creature can make it from its first day.';
    } else if (st === 'unfound') {
      status = '<b>Not found yet.</b> No creature in this world has made one.';
    } else {
      const HOW = { gather: 'gathered', ground: 'gathered', hunt: 'hunted', fish: 'caught', animal: 'given by animals',
        harvest: 'harvested', grow: 'grown', dry: 'dried', fill: 'filled' };
      const hows = [...new Set([...(X.procs.get(id) || []).map((p) => p.how), ...(it.sources || []).map((x) => x.how)]
        .map((h) => HOW[h] || h))];
      const list = hows.length > 1 ? hows.slice(0, -1).join(', ') + ' or ' + hows[hows.length - 1] : hows[0];
      status = `<b>No recipe.</b> ${list ? `It is ${esc(list)}.` : 'Nothing in the game makes it yet.'}`;
    }
    const census = X.d.world.items[id];
    let html = head(id, `${esc(id)} · ${esc(it.pack)} · tier ${it.tier}`);
    html += `<p class="cd-status st-${st}"><span class="st-mark" aria-hidden="true"></span><span>${status}</span></p>`;
    if (it.desc) html += `<p class="cd-desc">${esc(it.desc)}</p>`;
    if (r) {
      html += `<div class="cd-sec"><h3>Made from</h3><div class="cd-way"><div class="alm-items">` +
        Object.entries(r.inputs).map(([i, n]) => itemChip(i, n)).join('<span class="op">+</span>') + '</div>';
      const extra = [];
      if (r.tools.length) extra.push('holding ' + r.tools.map((t) => itemChip(t)).join(' '));
      if (r.station) extra.push('beside a ' + itemChip(r.station));
      if (extra.length) html += `<div class="alm-items how">${extra.join('<span class="op">·</span>')}</div>`;
      if (r.count > 1) html += `<div class="how">Makes <b>${fmt(r.count)}</b> at a time.</div>`;
      html += '</div></div>';
    }
    const procs = X.procs.get(id) || [];
    const src = it.sources || [];
    if (procs.length || src.length || (!r && it.hint)) {
      html += '<div class="cd-sec"><h3>Comes from</h3>';
      for (const p of procs) {
        html += `<div class="cd-way"><div class="alm-items"><span class="how"><b>${esc(cap(p.how))}</b></span>` +
          Object.keys(p.inputs).map((i) => itemChip(i)).join('') +
          (p.tools.length ? '<span class="op">holding</span>' + p.tools.map((t) => itemChip(t)).join('') : '') +
          (p.station ? '<span class="op">on a</span>' + itemChip(p.station) : '') + '</div>' +
          (p.note ? `<div class="how">${esc(cap(p.note))}.</div>` : '') + '</div>';
      }
      for (const s of src) html += sourceWay(s);
      if (!procs.length && !src.length && it.hint) html += `<div class="cd-way"><div class="how">${esc(cap(it.hint))}.</div></div>`;
      html += '</div>';
    }
    const used = it.used_in || [];
    const gathers = X.d.tree.edges.filter((e) => e.from === id && e.kind === 'gather_tool').map((e) => e.to);
    if (used.length || gathers.length) {
      const by = (as) => used.filter((u) => u.as === as).map((u) => u.output);
      const rows = [['Ingredient of', by('input')], ['Tool for', by('tool')], ['Station for', by('station')], ['Lets you gather', gathers]];
      html += '<div class="cd-sec"><h3>Used in</h3>' + rows.filter(([, ids]) => ids.length).map(([label, ids]) =>
        `<div class="cd-way"><div class="how">${label}</div><div class="alm-items">${[...new Set(ids)].map((o) => itemChip(o)).join('')}</div></div>`).join('') + '</div>';
    }
    if (r) {
      const knowers = X.knownBy.get(id) || [];
      html += `<div class="cd-sec"><h3>Who knows it · ${fmt(knowers.length)} of ${fmt(X.creatures.length)}</h3>`;
      html += knowers.length
        ? `<ul class="cd-who">${knowers.slice(0, 60).map((c) => `<li><span class="dot" style="--c:${esc(c.color)}"></span>${esc(c.name)}</li>`).join('')}</ul>` +
          (knowers.length > 60 ? `<p class="alm-note">and ${fmt(knowers.length - 60)} more</p>` : '')
        : '<p class="alm-note">Nobody yet. Someone could combine its way to it, or be taught by one who knows.</p>';
      html += '</div>';
    }
    html += '<div class="cd-sec"><h3>In the world now</h3><dl class="cd-kv">';
    html += `<dt>Carried</dt><dd>${fmt(census ? census.carried : 0)}</dd><dt>In stores</dt><dd>${fmt(census ? census.stored : 0)}</dd>` +
      `<dt>On the ground</dt><dd>${fmt(census ? census.ground : 0)}</dd>`;
    if (X.kinds.has(id)) html += `<dt>Placed on the map</dt><dd>${fmt(X.kinds.get(id).count)}</dd>`;
    if (it.food) html += `<dt>Food value</dt><dd>${fmt(it.food)}</dd>`;
    if (it.tags.length) html += `<dt>Tags</dt><dd>${it.tags.map(esc).join(', ')}</dd>`;
    if (it.aliases.length) html += `<dt>Also called</dt><dd>${it.aliases.map(esc).join(', ')}</dd>`;
    html += '</dl></div>';
    return html;
  }
  function sourceWay(s) {
    const tools = s.tools.length ? '<span class="op">needs</span>' + s.tools.map((t) => itemChip(t)).join('<span class="op">or</span>') : '';
    const amount = s.amount ? ` <span class="t-sub">${s.amount[0] === s.amount[1] ? fmt(s.amount[0]) : `${fmt(s.amount[0])}–${fmt(s.amount[1])}`} each time</span>` : '';
    let what;
    if (s.how === 'ground' || s.how === 'fish') {
      what = `<b>${s.how === 'fish' ? 'Fish in' : 'From the'} ${esc(s.source)}</b>`;
    } else {
      const verb = { gather: 'Gather from', hunt: 'Hunt', animal: 'From', harvest: 'Harvest' }[s.how] || cap(s.how);
      what = `<b>${verb}</b> <span class="alm-item ghost">${icon(s.source, 20)}<span>${esc(kindName(s.source))}</span></span>`;
    }
    return `<div class="cd-way"><div class="alm-items how">${what}${amount}${tools}</div>${s.note ? `<div class="how">${esc(cap(s.note))}.</div>` : ''}</div>`;
  }
  function designCard(id) {
    const X = S.X;
    const d = X.designs.get(id);
    const status = d.status === 'built' ? `<b>Built here</b>: ${plural(d.built, 'standing')}.` + (d.sites ? ` ${plural(d.sites, 'more site')} under way.` : '')
      : d.status === 'site' ? `<b>Being built</b>: ${plural(d.sites, 'site')} under way, none finished yet.`
        : '<b>Not built yet.</b> A creature lays out a site with <code>build</code>, then brings what it needs.';
    let html = head(id, `a building · ${esc(d.pack)} pack · tier ${d.tier}`);
    html += `<p class="cd-status st-${d.status}"><span class="st-mark" aria-hidden="true"></span><span>${status}</span></p>`;
    if (d.about) html += `<p class="cd-desc">${esc(cap(d.about))}.</p>`;
    html += `<div class="cd-sec"><h3>Needs${d.over_water ? ', for each step of water' : ''}</h3><div class="cd-way"><div class="alm-items">` +
      Object.entries(d.needs).map(([i, n]) => itemChip(i, n)).join('<span class="op">+</span>') + '</div></div></div>';
    html += `<div class="cd-sec"><h3>Facts</h3><dl class="cd-kv"><dt>Work</dt><dd>${plural(d.work, 'turn')} once it has everything</dd>` +
      `<dt>Roof</dt><dd>${d.roof ? 'yes: dry and warm inside' : 'no'}</dd>` +
      (d.over_water ? '<dt>Where</dt><dd>straight across deep water</dd>' : '') + '</dl></div>';
    const sites = X.d.world.sites.filter((s) => s.design === d.id);
    if (sites.length) html += '<div class="cd-sec"><h3>Sites under way</h3>' + sites.map(siteRow).join('') + '</div>';
    return html;
  }
  function siteRow(s) {
    const need = Object.values(s.needs).reduce((a, b) => a + b, 0) || 1;
    const have = Object.entries(s.needs).reduce((a, [i, n]) => a + Math.min(n, s.have[i] || 0), 0);
    const share = (have / need + (s.done || 0) / Math.max(1, s.work || 1)) / 2;
    return `<div class="cd-way"><div class="alm-items how"><span class="cs-meter" role="img" aria-label="${Math.round(share * 100)}% done">` +
      `<span class="have" style="width:${Math.max(2, share * 100)}%"></span><span class="left"></span></span>` +
      `<span class="t-sub">${fmt(have)} of ${fmt(need)} materials · ${fmt(s.done || 0)} of ${fmt(s.work || 0)} turns of work${s.by.length ? ' · by ' + s.by.map(esc).join(', ') : ''}</span></div></div>`;
  }

  /* ------------------------------------------------------------------ tech tree: pan and zoom */
  function applyTf() {
    const tf = S.tf;
    if (tf) $('tt-world').style.transform = `translate(${tf.x}px, ${tf.y}px) scale(${tf.k})`;
  }
  /** The whole tree in view; or, for the first view (readable), as much as fits at a scale you can read, from the
   *  left, where the tree begins. */
  function fit(animate, readable) {
    const L = layout();
    const vp = $('tt-viewport');
    const vw = vp.clientWidth || 800, vh = vp.clientHeight || 500;
    const all = Math.max(0.25, Math.min(1.1, (vw - 40) / L.W, (vh - 70) / L.H));
    const k = readable ? Math.min(1, Math.max(all, 0.82)) : all;
    const x = L.W * k <= vw - 40 ? (vw - L.W * k) / 2 : 20;
    setTf({ k, x, y: Math.max(14, (vh - 46 - L.H * k) / 2) }, animate);
  }
  function setTf(tf, animate) {
    const world = $('tt-world');
    S.tf = tf;
    if (animate) {
      world.style.transition = 'transform 0.28s cubic-bezier(0.16, 1, 0.3, 1)';
      clearTimeout(setTf.timer);
      setTf.timer = setTimeout(() => { world.style.transition = ''; }, 320);
    }
    applyTf();
  }
  function zoomAt(factor, cx, cy, animate) {
    const tf = S.tf;
    const k = Math.max(0.2, Math.min(2.6, tf.k * factor));
    const f = k / tf.k;
    setTf({ k, x: cx - (cx - tf.x) * f, y: cy - (cy - tf.y) * f }, animate);
  }
  function centerOn(id, animate) {
    const L = layout();
    const p = L.pos.get(id);
    const vp = $('tt-viewport');
    if (!p || !S.tf) return;
    const k = Math.max(S.tf.k, 0.8);
    // on a phone the card is a sheet over the lower part of the tree: centre in the strip above it
    const card = $('tt-card');
    const r = vp.getBoundingClientRect();
    const visible = NARROW.matches && !card.hidden ? Math.max(80, card.getBoundingClientRect().top - r.top) : vp.clientHeight;
    setTf({ k, x: vp.clientWidth / 2 - (p.x + NODE_W / 2) * k, y: visible / 2 - (p.y + NODE_H / 2) * k }, animate);
  }

  function wireViewport() {
    const vp = $('tt-viewport');
    const pts = new Map();
    let drag = null, pinch = null, moved = false;
    vp.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.tt-zoom')) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      vp.setPointerCapture(e.pointerId);
      moved = false;
      if (pts.size === 1) drag = { x: e.clientX, y: e.clientY, tx: S.tf.x, ty: S.tf.y, target: e.target.closest('.tn') };
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: S.tf.k };
        drag = null;
      }
    });
    vp.addEventListener('pointermove', (e) => {
      if (!pts.has(e.pointerId)) {
        const n = e.target.closest('.tn');
        const id = n ? n.dataset.id : null;
        if (id !== S.hover) { S.hover = id; paintFocus(); }
        return;
      }
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pts.size === 2) {
        const [a, b] = [...pts.values()];
        const r = vp.getBoundingClientRect();
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        zoomAt((pinch.k * d / pinch.d) / S.tf.k, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
        moved = true;
      } else if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (!moved && Math.hypot(dx, dy) < 4) return;
        moved = true;
        vp.classList.add('is-dragging');
        setTf({ k: S.tf.k, x: drag.tx + dx, y: drag.ty + dy });
      }
    });
    const end = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.delete(e.pointerId);
      vp.classList.remove('is-dragging');
      if (pts.size < 2) pinch = null;
      if (pts.size === 0) {
        if (!moved && drag && e.type === 'pointerup') {
          if (drag.target) select(drag.target.dataset.id, false);
          else if (S.sel) select(null);
        }
        drag = null;
      }
    };
    vp.addEventListener('pointerup', end);
    vp.addEventListener('pointercancel', end);
    vp.addEventListener('pointerleave', () => { if (S.hover && !pts.size) { S.hover = null; paintFocus(); } });
    vp.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = vp.getBoundingClientRect();
      if (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(e.deltaY)) {  // a trackpad's sideways swipe pans
        setTf({ k: S.tf.k, x: S.tf.x - e.deltaX, y: S.tf.y });
        return;
      }
      const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomAt(Math.exp(-delta * (e.ctrlKey ? 0.01 : 0.0022)), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    vp.addEventListener('keydown', (e) => {
      const step = 60;
      const r = vp.getBoundingClientRect();
      const move = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
      if (move && e.target === vp) { e.preventDefault(); setTf({ k: S.tf.k, x: S.tf.x + move[0], y: S.tf.y + move[1] }, true); }
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(1.25, r.width / 2, r.height / 2, true); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomAt(0.8, r.width / 2, r.height / 2, true); }
      else if (e.key === '0') { e.preventDefault(); fit(true); }
      else if (e.key === 'Enter' && e.target.closest('.tn')) { e.preventDefault(); select(e.target.closest('.tn').dataset.id, false); }
    });
    vp.addEventListener('focusin', (e) => {
      const n = e.target.closest('.tn');
      if (n && n.dataset.id !== S.hover) { S.hover = n.dataset.id; paintFocus(); }
    });
    vp.querySelector('.tt-zoom').addEventListener('click', (e) => {
      const b = e.target.closest('[data-zoom]');
      if (!b) return;
      const r = vp.getBoundingClientRect();
      if (b.dataset.zoom === 'fit') fit(true);
      else zoomAt(b.dataset.zoom === 'in' ? 1.25 : 0.8, r.width / 2, r.height / 2, true);
    });
  }

  function select(id, center) {
    S.sel = id;
    S.hover = null;
    writeHash();
    renderCard();
    paintFocus();
    if (id && center) {
      if (S.view === 'graph') centerOn(id, true);
      else {
        const list = $('tt-list');
        const row = list.querySelector(`.tt-row[data-id="${CSS.escape(id)}"]`);
        if (row) list.scrollTo({ top: Math.max(0, row.offsetTop - list.clientHeight / 3), behavior: 'smooth' });
      }
    }
  }
  /** Go to a thing from anywhere: the tree tab, its node centred and its card open. */
  function go(id) {
    if (!S.X || !(S.X.items.has(id) || S.X.designs.has(id))) return;
    if (!matches(id)) {  // show it even if the filters hid it
      S.packs.add(packOf(id));
      S.status.add(GROUP_OF[statusOf(id)]);
      S.q = '';
      $('tt-search').value = '';
    }
    if (S.tab !== 'tree') { S.dirty.add('tree'); setTab('tree'); } else renderTreeBar();
    select(id, true);
  }

  /* ------------------------------------------------------------------ things */
  function renderThings() {
    const X = S.X;
    const groups = X.d.world.groups;
    const q = S.thingsQ;
    const shown = (k) => S.thingsGroups.has(k.category) &&
      (!q || k.name.toLowerCase().includes(q) || k.id.includes(q.replace(/\s+/g, '_')) || k.aliases.some((a) => a.toLowerCase().includes(q)));
    const order = Object.keys(groups);
    let html = '<div class="alm-doc">';
    html += '<h2 class="alm-h2">Every kind of thing<small>by pack · counts are what stands on the map now</small></h2>';
    html += '<div class="alm-filter"><label class="alm-search"><span class="sr-only">Find a kind of thing</span>' +
      `<input type="search" id="th-search" placeholder="Find a kind of thing…" value="${esc(q)}" autocomplete="off" spellcheck="false"></label>` +
      '<div class="alm-chips" role="group" aria-label="Show by group">' + order.map((g) => {
        const n = X.d.kinds.filter((k) => k.category === g).length;
        return n ? `<button type="button" class="alm-chip" data-group="${g}" aria-pressed="${S.thingsGroups.has(g)}">${esc(groups[g].label)}<span class="n">${fmt(n)}</span></button>` : '';
      }).join('') + '</div></div>';
    let any = false;
    for (const p of X.d.packs) {
      const kinds = X.d.kinds.filter((k) => k.pack === p.id && shown(k))
        .sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category) || a.name.localeCompare(b.name));
      if (!kinds.length) continue;
      any = true;
      const total = kinds.reduce((a, k) => a + k.count, 0);
      html += `<section class="th-pack"><div class="th-pack-head"><h2>${esc(p.id)}</h2><p>${plural(kinds.length, 'kind')} · ${fmt(total)} on the map</p></div>` +
        `<p class="alm-lede">${esc(p.about)}</p>` +
        '<table class="alm-table"><thead><tr><th class="th-look"><span class="sr-only">Look</span></th><th>Thing</th><th class="r">On the map</th><th>Gives</th><th>Behaviour</th></tr></thead><tbody>';
      for (const k of kinds) html += thingRow(k);
      html += '</tbody></table></section>';
    }
    if (!any) html += '<p class="alm-empty">No kind of thing matches. Clear the search or turn a group back on.</p>';
    html += '</div>';
    const pane = $('pane-things');
    const focused = document.activeElement && document.activeElement.id === 'th-search';
    const caret = focused ? document.activeElement.selectionStart : null;
    pane.innerHTML = html;
    if (focused) { const i = $('th-search'); i.focus(); i.setSelectionRange(caret, caret); }
  }
  /** An item chip with the amount it comes in ("1–3"), kept together on one line. */
  const amountChip = (i, lo, hi) =>
    `<span class="amt">${itemChip(i, 0)}<span class="t-sub">${lo === hi ? fmt(lo) : `${fmt(lo)}–${fmt(hi)}`}</span></span>`;
  function thingRow(k) {
    const X = S.X;
    const group = X.d.world.groups[k.category];
    let gives = '';
    if (k.yields) {
      const y = k.yields;
      gives += '<div class="alm-items">' + Object.entries(y.items).map(([i, [lo, hi]]) => amountChip(i, lo, hi)).join('') + '</div>';
      const bits = [`${plural(y.uses, 'gathering')} before it's spent`];
      if (y.tool) bits.push('needs ' + nameOf(y.tool));
      if (y.becomes) bits.push(`then becomes ${kindName(y.becomes)}`);
      if (y.regrow) bits.push(`grows back in ${fmt(y.regrow)} ticks`);
      gives += `<div class="t-sub">${esc(bits.join(' · '))}</div>`;
    } else if (k.game) {
      gives += '<div class="alm-items"><span class="t-sub">hunted:</span>' + Object.entries(k.game.gives || {}).map(([i, [lo, hi]]) => amountChip(i, lo, hi)).join('') + '</div>';
    } else if (k.gives.length) {
      gives += '<div class="alm-items">' + k.gives.map((i) => itemChip(i, 0)).join('') + '</div>';
      const tools = k.gives.flatMap((i) => ((X.items.get(i) || {}).sources || []).filter((s) => s.source === k.id && s.tools.length).map((s) => `${nameOf(i)} needs ${s.tools.map(nameOf).join(' or ')}`));
      if (tools.length) gives += `<div class="t-sub">${esc(tools.join(' · '))}</div>`;
    } else {
      gives = '<span class="t-sub">nothing</span>';
    }
    const be = [];
    if (k.animal) {
      be.push(k.wild ? '<b>Wild game</b>: never tamed, only hunted' : '<b>Farm animal</b>: fed often, it comes to trust you');
      if (k.wary) be.push(`keeps ${plural(k.wary, 'step')} from strangers${k.flee ? `, bolts ${plural(k.flee, 'step')} when they come closer` : ''}`);
      if (k.game && k.game.hit) be.push('hit by ' + Object.entries(k.game.hit).map(([w, p]) => `${nameOf(w)} ${Math.round(p * 100)}%`).join(', '));
      const tamed = (X.d.world.tamed || {})[k.id];
      if (tamed) be.push(`<b>${fmt(tamed)}</b> tamed now`);
    }
    if (k.habitat) {
      const tiles = [...(k.habitat.tiles || '')].map((t) => TILE_WORDS[t] || t).join(', ');
      be.push(`lives on ${esc(tiles)}${k.habitat.per_4096 ? ` · about ${fmt(k.habitat.per_4096)} per 64×64` : ''}`);
    }
    const flags = [];
    if (k.blocking) flags.push('blocks the way');
    if (k.store) flags.push('a store');
    if (k.station) flags.push('a station');
    if (k.water) flags.push('water source');
    if (k.over_water) flags.push('spans water');
    if (k.carvable) flags.push('can be carved');
    if (k.glow) flags.push('glows at night');
    if (X.items.has(k.id) && X.items.get(k.id).placeable) flags.push('placed from an item');
    const crops = k.id === 'crop' ? Object.entries(X.d.world.crops || {}).map(([c, n]) => `${fmt(n)} ${c}`).join(', ') : '';
    return `<tr class="th-row" data-kind="${esc(k.id)}"><td class="th-look"><span class="look">${lookHTML(k.id)}</span></td>` +
      `<td class="th-name"><span class="t-name">${esc(cap(k.name))}</span><span class="t-id">${esc(k.id)} · ${esc(group ? group.label : k.category)}</span>` +
      (k.look ? `<span class="t-id">look: ${esc(k.look)}</span>` : '') + '</td>' +
      `<td class="r th-count"><span class="t-n${k.count ? '' : ' zero'}">${fmt(k.count)}</span>${crops ? `<span class="t-id">${esc(crops)}</span>` : ''}</td>` +
      `<td data-th="Gives">${gives}</td>` +
      `<td data-th="Behaviour"><div class="th-behave">${be.map((b) => `<span>${b}</span>`).join('') || (flags.length ? '' : '<span class="t-sub">stays put</span>')}</div>` +
      (flags.length ? `<div class="th-flags">${flags.map((f) => `<span class="badge">${esc(f)}</span>`).join('')}</div>` : '') + '</td></tr>';
  }

  /* ------------------------------------------------------------------ verbs */
  function renderVerbs() {
    const X = S.X;
    const verbs = [...X.d.verbs];
    if (S.verbSort === 'used') verbs.sort((a, b) => b.used.tries - a.used.tries || a.name.localeCompare(b.name));
    const max = Math.max(1, ...verbs.map((v) => v.used.tries));
    const total = verbs.reduce((a, v) => a + v.used.tries, 0);
    const since = X.d.world.verbs_since;
    let html = '<div class="alm-doc"><div class="cs-head"><h2 class="alm-h2">Every verb<small>' +
      `${plural(verbs.length, 'action')} a mind may choose · ${plural(total, 'choice')} counted ${since ? `since tick ${fmt(since)}` : 'since the world began'}</small></h2>` +
      '<span class="alm-seg" role="radiogroup" aria-label="Order" id="vb-sort">' +
      `<button type="button" role="radio" data-sort="schema" aria-checked="${S.verbSort === 'schema'}">In schema order</button>` +
      `<button type="button" role="radio" data-sort="used" aria-checked="${S.verbSort === 'used'}">Most used</button></span></div>`;
    html += '<p class="alm-lede">The tip is the line a creature reads; the last column says when it reads it. Every verb works whether it was shown or not.</p>';
    html += '<table class="alm-table"><thead><tr><th>Verb</th><th>Pack</th><th class="vb-used">Chosen</th><th>Tip</th><th>When it\'s shown</th></tr></thead><tbody>';
    for (const v of verbs) {
      const u = v.used;
      const ok = u.tries ? Math.round((u.ok / u.tries) * 100) : null;
      const models = Object.entries(u.by_model).sort((a, b) => b[1] - a[1]).map(([m, n]) => `${m} ${fmt(n)}`).join(' · ');
      html += `<tr><td><span class="vb-verb">${esc(v.name)}</span>${v.aliases.length ? `<span class="vb-alias" title="${esc(v.aliases.join(', '))}">also ${esc(v.aliases.slice(0, 4).join(', '))}${v.aliases.length > 4 ? ` +${v.aliases.length - 4}` : ''}</span>` : ''}</td>` +
        `<td data-th="Pack"><span class="badge">${esc(v.pack)}</span></td>` +
        `<td class="vb-used" data-th="Chosen"><div class="vb-bar" ${models ? `data-tip-title="${esc(v.name)}" data-tip="${esc(models)}"` : ''}><span class="t-n${u.tries ? '' : ' zero'}">${fmt(u.tries)}</span>` +
        `<span class="vb-track">${u.tries ? `<span class="vb-fill" style="width:${(u.tries / max) * 100}%"></span>` : ''}</span></div>` +
        (ok != null ? `<span class="vb-ok">${ok}% worked</span>` : '') + '</td>' +
        `<td class="vb-tip" data-th="Tip">${esc(v.tip)}</td><td class="vb-shown" data-th="Shown">${esc(v.shown)}</td></tr>`;
      for (const use of v.uses) {
        html += `<tr class="vb-use"><td><span class="vb-verb">↳ ${esc(use.name)}</span></td><td></td><td></td>` +
          `<td class="vb-tip" data-th="Tip">${esc(use.line)}</td><td class="vb-shown" data-th="Shown">${esc(use.shown)}</td></tr>`;
      }
    }
    html += '</tbody></table></div>';
    $('pane-verbs').innerHTML = html;
  }

  /* ------------------------------------------------------------------ census */
  function bars(rows, max, cls) {
    return '<ul class="cs-bars">' + rows.map((r) =>
      `<li class="cs-bar" data-tip-title="${esc(r.name)}" data-tip="${esc(r.tip)}"><span class="cs-label">${r.icon}<span class="nm">${esc(r.name)}</span></span>` +
      `<span class="cs-val"><span class="cs-track">${r.segs.map(([c, n]) => n > 0 ? `<span class="cs-seg ${c || cls}" style="width:calc(${(n / max) * 100}% - 2px)"></span>` : '').join('')}</span>` +
      `<span class="cs-n">${fmt(r.total)}</span></span></li>`).join('') + '</ul>';
  }
  function renderCensus() {
    const X = S.X;
    const w = X.d.world;
    const things = Object.values(w.groups).reduce((a, g) => a + g.count, 0);
    const awake = X.creatures.filter((c) => !c.asleep).length;
    const inv = w.discoveries.filter((d) => d.invented).length;
    let html = '<div class="alm-doc"><h2 class="alm-h2">The world now<small>' + `day ${fmt(X.d.day)} · tick ${fmt(X.d.tick)}</small></h2>`;
    html += '<ul class="cs-strip">' + [
      [X.creatures.length, `creatures · ${fmt(awake)} awake`], [things, 'things on the map'],
      [w.discoveries.length - inv, 'recipes discovered'], [inv, 'inventions'], [w.buildings.length, 'buildings'],
      [w.sites.length, 'sites under way'],
    ].map(([v, l]) => `<li><span class="v">${fmt(v)}</span><span class="l">${esc(l)}</span></li>`).join('') + '</ul>';

    html += '<h2 class="alm-h2">On the map<small>each group on its own scale</small></h2><div class="cs-grid">';
    for (const [g, grp] of Object.entries(w.groups)) {
      const rows = Object.entries(grp.kinds).sort((a, b) => b[1] - a[1]);
      if (!rows.length) continue;
      const max = rows[0][1];
      const top = rows.slice(0, 9);
      const rest = rows.slice(9);
      html += `<section class="cs-group"><h3>${esc(grp.label)} <span class="t">${fmt(grp.count)}</span></h3>` +
        bars(top.map(([k, n]) => ({ name: cap(kindName(k)), icon: icon(k, 20), segs: [['bar', n]], total: n, tip: `${fmt(n)} on the map` })), max, 'bar') +
        (rest.length ? `<p class="alm-note">and ${plural(rest.length, 'other kind')}: ${esc(rest.map(([k, n]) => `${kindName(k)} ${fmt(n)}`).join(', '))}</p>` : '') + '</section>';
    }
    const empty = Object.entries(w.groups).filter(([, g]) => !g.count).map(([, g]) => g.label.toLowerCase());
    html += '</div>' + (empty.length ? `<p class="alm-note">None on the map right now: ${esc(empty.join(', '))}.</p>` : '');

    const items = Object.entries(w.items).map(([id, c]) => ({ id, ...c, total: c.carried + c.stored + c.ground })).sort((a, b) => b.total - a.total);
    html += '<div class="cs-head"><h2 class="alm-h2">Carried, stored and on the ground<small>' + `${plural(items.length, 'kind')} of item</small></h2>` +
      `<span class="alm-seg" role="radiogroup" aria-label="Show as" id="cs-items-view"><button type="button" role="radio" data-items="chart" aria-checked="${!S.itemsTable}">Chart</button>` +
      `<button type="button" role="radio" data-items="table" aria-checked="${S.itemsTable}">Table</button></span></div>`;
    if (!items.length) {
      html += '<p class="alm-empty">Nobody carries or keeps anything yet.</p>';
    } else if (S.itemsTable) {
      html += '<table class="alm-table"><thead><tr><th>Item</th><th class="r">Carried</th><th class="r">In stores</th><th class="r">On the ground</th><th class="r">All</th></tr></thead><tbody>' +
        items.map((i) => `<tr><td><button type="button" class="alm-item" data-go="${esc(i.id)}">${icon(i.id, 20)}<span>${esc(nameOf(i.id))}</span></button></td>` +
          `<td class="r num" data-th="Carried">${fmt(i.carried)}</td><td class="r num" data-th="In stores">${fmt(i.stored)}</td><td class="r num" data-th="On the ground">${fmt(i.ground)}</td><td class="r num" data-th="All"><b>${fmt(i.total)}</b></td></tr>`).join('') +
        '</tbody></table>';
    } else {
      html += '<ul class="cs-legend"><li><span class="sw" style="background:var(--s-carried)"></span>carried</li>' +
        '<li><span class="sw" style="background:var(--s-stored)"></span>in stores</li><li><span class="sw" style="background:var(--s-ground)"></span>on the ground</li></ul>';
      const top = items.slice(0, 24);
      html += '<div class="cs-wide">' + bars(top.map((i) => ({
        name: nameOf(i.id), icon: icon(i.id, 20), total: i.total,
        segs: [['carried', i.carried], ['stored', i.stored], ['ground', i.ground]],
        tip: `${fmt(i.carried)} carried · ${fmt(i.stored)} in stores · ${fmt(i.ground)} on the ground`,
      })), top[0].total) + '</div>';
      if (items.length > 24) html += `<p class="alm-note">${plural(items.length - 24, 'more kind')} in the table view.</p>`;
    }

    html += '<h2 class="alm-h2">Buildings</h2>';
    const designs = X.d.designs;
    if (!w.buildings.length && !w.sites.length) {
      html += '<p class="alm-empty">Nothing built yet. A creature lays out a site with <code>build</code> (a tent, a hut, a storehouse, a workshop, a well or a bridge), then brings what it needs; anyone can help.</p>';
    } else {
      html += '<div class="cs-wide">' + bars(designs.filter((d) => d.built).map((d) => ({ name: d.name, icon: icon('design:' + d.id, 20), segs: [['bar', d.built]], total: d.built, tip: `${plural(d.built, 'standing')}` })),
        Math.max(1, ...designs.map((d) => d.built)), 'bar') + '</div>';
      if (w.sites.length) html += '<h3 class="alm-h3">Sites under way</h3>' + w.sites.map((s) => `<div class="alm-items"><b>${esc(nameOf('design:' + s.design))}</b></div>${siteRow(s)}`).join('');
    }
    const tamed = Object.entries(w.tamed || {});
    const crops = Object.entries(w.crops || {});
    if (tamed.length || crops.length) {
      html += '<h3 class="alm-h3">Tended</h3><div class="alm-items">' +
        tamed.map(([k, n]) => `<span class="alm-item ghost">${icon(k, 20)}<span>${fmt(n)} tamed ${esc(kindName(k))}</span></span>`).join('') +
        crops.map(([c, n]) => `<span class="alm-item ghost">${icon(c, 20)}<span>${fmt(n)} ${esc(c)} growing</span></span>`).join('') + '</div>';
    }

    html += '<h2 class="alm-h2">Discoveries<small>first makes and inventions, in order</small></h2>';
    if (!w.discoveries.length) {
      html += '<p class="alm-empty">Nothing discovered yet. When a creature combines its way to something new, it appears here, with who and when.</p>';
    } else {
      html += '<div class="cs-tl" id="cs-tl"></div>';
      html += '<ul class="cs-found">' + [...w.discoveries].reverse().map((d) =>
        `<li><span class="when">day ${fmt(d.day)}<br>tick ${fmt(d.tick)}</span>${icon(d.item, 22)}` +
        `<span class="what"><button type="button" class="alm-item ghost" data-go="${esc(d.item)}"><span>${esc(nameOf(d.item))}</span></button> ${d.invented ? 'invented' : 'discovered'}</span>` +
        `<span class="who"><span class="dot" style="--c:${esc(X.modelColor.get(d.model) || '#b9aebb')}"></span>${esc(d.by || 'someone')} <span class="t-sub">${esc(d.model || '')}</span></span></li>`).join('') + '</ul>';
    }
    html += '</div>';
    $('pane-census').innerHTML = html;
    if (w.discoveries.length) drawTimeline();
  }

  function drawTimeline() {
    const X = S.X;
    const box = $('cs-tl');
    if (!box) return;
    const found = X.d.world.discoveries;
    const W = Math.max(320, box.clientWidth);
    const models = [...new Set(found.map((d) => d.model || '?'))]
      .sort((a, b) => found.filter((d) => d.model === b).length - found.filter((d) => d.model === a).length);
    const LANE = 30, LEFT = Math.min(150, Math.max(90, W * 0.18)), TOPPAD = 24, R = 5;
    const t0 = (dayOf(Math.min(...found.map((d) => d.tick))) - 1) * DAY_TICKS, t1 = Math.max(X.d.tick, t0 + 1);
    const span = Math.max(1, t1 - t0);
    const x = (t) => LEFT + ((t - t0) / span) * (W - LEFT - 16);
    const H = TOPPAD + models.length * LANE + 6;
    let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Discoveries over time, one row per model; the list below has every one">`;
    const firstDay = dayOf(t0), lastDay = dayOf(t1);
    const every = Math.max(1, Math.ceil((lastDay - firstDay + 1) / 10));
    for (let d = firstDay; d <= lastDay; d++) {
      const t = (d - 1) * DAY_TICKS;
      svg += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${TOPPAD - 6}" y2="${H - 4}"/>`;
      if ((d - firstDay) % every === 0 && x(t) < W - 70) svg += `<text class="axis" x="${x(t) + 4}" y="${TOPPAD - 10}">Day ${d}</text>`;
    }
    svg += `<text class="axis" x="${W - 16}" y="${TOPPAD - 10}" text-anchor="end">now</text>`;
    models.forEach((m, i) => {
      const cy = TOPPAD + i * LANE + LANE / 2;
      svg += `<line class="grid" x1="${LEFT}" x2="${W - 16}" y1="${cy}" y2="${cy}"/>`;
      svg += `<text class="lane" x="0" y="${cy + 4}">${esc(m.length > 18 ? m.slice(0, 17) + '…' : m)}</text>`;
    });
    for (const d of found) {
      const cy = TOPPAD + models.indexOf(d.model || '?') * LANE + LANE / 2, cx = x(d.tick);
      const color = X.modelColor.get(d.model) || '#b9aebb';
      const tip = `${d.invented ? 'invented' : 'discovered'} by ${d.by || 'someone'} (${d.model || '?'}) · day ${fmt(d.day)}, tick ${fmt(d.tick)}`;
      svg += `<circle class="hit" cx="${cx}" cy="${cy}" r="12" data-go="${esc(d.item)}" data-tip-title="${esc(nameOf(d.item))}" data-tip="${esc(tip)}"/>`;
      svg += d.invented
        ? `<rect class="pt inv" x="${cx - R}" y="${cy - R}" width="${R * 2}" height="${R * 2}" transform="rotate(45 ${cx} ${cy})" fill="${esc(color)}" pointer-events="none"/>`
        : `<circle class="pt" cx="${cx}" cy="${cy}" r="${R}" fill="${esc(color)}" pointer-events="none"/>`;
    }
    svg += '</svg>';
    box.innerHTML = svg + '<p class="alm-note">A dot is a first make, a diamond an invention. Hover for who and when; click to see it in the tree.</p>';
  }

  /* ------------------------------------------------------------------ packs */
  function renderPacks() {
    const X = S.X;
    const d = X.d;
    const by = (list, pack) => list.filter((x) => x.pack === pack);
    let html = '<div class="alm-doc"><h2 class="alm-h2">Installed packs<small>what each one adds to the world</small></h2><div class="pk-list">';
    const COUNTS = [['items', 'item'], ['recipes', 'recipe'], ['kinds', 'kind'], ['verbs', 'verb'], ['techniques', 'tip'],
      ['designs', 'design'], ['systems', 'system'], ['perception', 'perception line'], ['populate', 'populate hook']];
    for (const p of d.packs) {
      const systems = by(d.systems, p.id), lines = by(d.perception, p.id), pops = by(d.populate, p.id), verbs = by(d.verbs, p.id);
      const key = 'pk-' + p.id;
      html += `<article class="pk"><h3>${esc(p.id)}<small>${p.id === 'core' ? 'swarmworld/world, data/*.json' : p.id === 'invented' ? 'made by creatures' : 'packs/' + esc(p.id)}</small></h3><div>` +
        `<p>${esc(p.about)}</p><ul class="pk-counts">${COUNTS.map(([k, one]) => `<li class="${p[k] ? '' : 'zero'}"><b>${fmt(p[k] || 0)}</b>${esc(p[k] === 1 ? one : one + 's')}</li>`).join('')}</ul>`;
      if (systems.length || lines.length || pops.length || verbs.length) {
        html += `<details data-key="${key}"${S.open.has(key) ? ' open' : ''}><summary>What it runs</summary><ul class="pk-parts">` +
          verbs.map((v) => `<li><span class="k">verb</span><span><b class="mono">${esc(v.name)}</b> ${esc(v.tip.replace(new RegExp('^' + v.name + '\\b:?\\s*'), ''))}</span></li>`).join('') +
          systems.map((s) => `<li><span class="k">system</span><span><b>${esc(s.name)}</b>, every ${plural(s.every, 'tick')}${s.about ? ': ' + esc(s.about) : ''}</span></li>`).join('') +
          lines.map((l) => `<li><span class="k">perception ${fmt(l.priority)}</span><span><b>${esc(l.name)}</b>${l.about ? ': ' + esc(l.about) : ''}</span></li>`).join('') +
          pops.map((l) => `<li><span class="k">populate</span><span><b>${esc(l.name)}</b>${l.about ? ': ' + esc(l.about) : ''}</span></li>`).join('') +
          '</ul></details>';
      }
      html += '</div></article>';
    }
    html += '</div><h2 class="alm-h2">Harness layers<small>how creatures are helped to think, split across each model\'s creatures for the live trial</small></h2><div class="pk-list">';
    for (const h of d.harness) {
      const where = !h.in_world ? 'not in this world' : h.everyone ? 'every creature' : `${plural(h.creatures, 'creature')} of ${fmt(X.creatures.length)}`;
      html += `<article class="pk"><h3>${esc(h.name)}<small>${esc(where)}</small></h3><div><p>${esc(h.about)}</p></div></article>`;
    }
    html += '</div></div>';
    $('pane-packs').innerHTML = html;
  }

  /* ------------------------------------------------------------------ roadmap */
  function renderRoadmap() {
    const rm = S.X.d.roadmap;
    let html = '<div class="alm-doc">';
    if (!rm.issues.length) {
      html += '<h2 class="alm-h2">Roadmap</h2><p class="alm-empty">No backlog found. The roadmap is read from <code>issues/README.md</code> beside the world\'s code.</p></div>';
      $('pane-roadmap').innerHTML = html;
      return;
    }
    const pri = (p) => { const m = /P(\d)/.exec(p || ''); return m ? +m[1] : 9; };
    const SECS = [['progress', 'In progress'], ['open', 'Open'], ['fixed', 'Fixed']];
    const n = rm.counts;
    html += `<h2 class="alm-h2">Roadmap<small>${fmt(n.progress || 0)} in progress · ${fmt(n.open || 0)} open · ${fmt(n.fixed || 0)} fixed</small></h2>`;
    html += '<p class="alm-lede">The backlog from <code>issues/</code>: what\'s being built, what\'s waiting, and what\'s been fixed. Highest priority first.</p>';
    for (const [state, label] of SECS) {
      const list = rm.issues.filter((i) => i.state === state).sort((a, b) => pri(a.priority) - pri(b.priority) || a.number.localeCompare(b.number));
      if (!list.length) continue;
      const key = 'rm-' + state;
      html += `<details class="rm-sec" data-key="${key}"${S.open.has(key) ? ' open' : ''}><summary><h2 class="alm-h2">${label}<small>${fmt(list.length)}</small></h2></summary><ul class="rm-list">`;
      for (const i of list) {
        const p = pri(i.priority);
        const extra = i.status && i.status.toLowerCase() !== state && i.status.toLowerCase() !== label.toLowerCase() ? i.status : '';
        html += `<li class="rm-item ${state}"><span class="rm-num">${esc(i.number)}</span><span class="pri p${p < 9 ? p : 'x'}" title="Priority ${esc(i.priority)}">${esc(i.priority || '–')}</span>` +
          `<span class="rm-label">${esc(i.label)}</span><div class="rm-body"><p class="rm-title">${md(i.title)}</p>` +
          (i.summary ? `<p class="rm-sum">${md(i.summary)}</p>` : '') +
          (extra ? `<p class="rm-state">${esc(cap(extra))}</p>` : '') + '</div></li>';
      }
      html += '</ul></details>';
    }
    html += '</div>';
    $('pane-roadmap').innerHTML = html;
  }

  /* ------------------------------------------------------------------ tooltip */
  function wireTooltip() {
    const tip = $('alm-tip');
    let on = null;
    document.addEventListener('pointerover', (e) => {
      const el = e.target.closest && e.target.closest('[data-tip]');
      if (el === on) return;
      on = el;
      if (!el) { tip.hidden = true; return; }
      tip.textContent = '';
      if (el.dataset.tipTitle) { const b = document.createElement('b'); b.textContent = el.dataset.tipTitle; tip.appendChild(b); }
      tip.appendChild(document.createTextNode(el.dataset.tip));
      tip.hidden = false;
      place(e);
    });
    document.addEventListener('pointermove', (e) => { if (on) place(e); });
    function place(e) {
      const r = tip.getBoundingClientRect();
      let x = e.clientX + 14, y = e.clientY + 16;
      if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 12;
      if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 12;
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    }
  }

  /* ------------------------------------------------------------------ wiring */
  function wire() {
    $('tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) setTab(b.dataset.tab); });
    $('tabs').addEventListener('keydown', (e) => {
      const i = TABS.indexOf(S.tab);
      if (e.key === 'ArrowRight') setTab(TABS[(i + 1) % TABS.length], true);
      else if (e.key === 'ArrowLeft') setTab(TABS[(i + TABS.length - 1) % TABS.length], true);
    });
    $('skin-switch').addEventListener('click', (e) => {
      const b = e.target.closest('[data-skin]');
      if (b && b.dataset.skin !== SK.name) setSkin(b.dataset.skin, true);
    });
    $('refresh-btn').addEventListener('click', () => load(true));
    $('back-link').href = './' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : '');

    $('tt-search').addEventListener('input', (e) => {
      S.q = e.target.value.trim().toLowerCase();
      paintFocus();
    });
    $('tt-search').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const hit = [...S.X.nodes.keys()].filter((id) => matches(id) && searchHit(id))
          .sort((a, b) => nameOf(a).length - nameOf(b).length)[0];
        if (hit) select(hit, true);
      } else if (e.key === 'Escape') { e.target.value = ''; S.q = ''; paintFocus(); }
    });
    $('tt-status').addEventListener('click', (e) => {
      const b = e.target.closest('[data-status]');
      if (!b) return;
      const k = b.dataset.status;
      if (S.status.has(k)) S.status.delete(k); else S.status.add(k);
      b.setAttribute('aria-pressed', String(S.status.has(k)));
      paintFocus();
    });
    $('tt-packs').addEventListener('click', (e) => {
      const b = e.target.closest('[data-pack]');
      if (!b) return;
      const k = b.dataset.pack;
      if (S.packs.has(k)) S.packs.delete(k); else S.packs.add(k);
      b.setAttribute('aria-pressed', String(S.packs.has(k)));
      paintFocus();
    });
    $('tt-view').addEventListener('click', (e) => {
      const b = e.target.closest('[data-view]');
      if (!b || b.dataset.view === S.view) return;
      S.view = b.dataset.view;
      S.dirty.add('tree');
      render();
      if (S.view === 'graph' && S.sel) centerOn(S.sel, false);
    });
    $('tt-list').addEventListener('click', (e) => { const r = e.target.closest('.tt-row'); if (r) select(r.dataset.id, false); });
    $('tt-card').addEventListener('click', (e) => {
      if (e.target.closest('[data-close]')) { select(null); return; }
    });
    // any item chip anywhere goes to that thing in the tree
    document.addEventListener('click', (e) => {
      const g = e.target.closest && e.target.closest('[data-go]');
      if (g) { e.preventDefault(); go(g.dataset.go); }
    });
    document.addEventListener('input', (e) => {
      if (e.target.id === 'th-search') { S.thingsQ = e.target.value.trim().toLowerCase(); S.dirty.add('things'); render(); }
    });
    document.addEventListener('click', (e) => {
      const g = e.target.closest('[data-group]');
      if (g) {
        const k = g.dataset.group;
        if (S.thingsGroups.has(k)) S.thingsGroups.delete(k); else S.thingsGroups.add(k);
        S.dirty.add('things'); render();
      }
      const s = e.target.closest('#vb-sort [data-sort]');
      if (s) { S.verbSort = s.dataset.sort; S.dirty.add('verbs'); render(); }
      const iv = e.target.closest('#cs-items-view [data-items]');
      if (iv) { S.itemsTable = iv.dataset.items === 'table'; S.dirty.add('census'); render(); }
    });
    document.addEventListener('toggle', (e) => {
      const k = e.target.dataset && e.target.dataset.key;
      if (k) { if (e.target.open) S.open.add(k); else S.open.delete(k); }
    }, true);
    document.addEventListener('keydown', (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName);
      if (e.key === 'Escape' && S.sel && S.tab === 'tree' && !typing) { select(null); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '/' && S.tab === 'tree') { e.preventDefault(); $('tt-search').focus(); }
      else if (e.key === 'r' || e.key === 'R') load(true);
    });
    window.addEventListener('hashchange', () => {
      const before = S.sel;
      readHash();
      setTab(S.tab);
      if (S.tab === 'tree' && S.sel !== before) select(S.sel, true);
    });
    let resizeT;
    window.addEventListener('resize', () => {
      clearTimeout(resizeT);
      resizeT = setTimeout(() => { if (S.tab === 'census') drawTimeline(); }, 150);
    });
    NARROW.addEventListener('change', () => {
      S.view = NARROW.matches ? 'list' : 'graph';
      S.dirty.add('tree');
      render();
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && Date.now() - S.fetchedAt > REFRESH_MS) load();
    });
    setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
    setInterval(renderClock, 5000);
  }

  async function boot() {
    window.scrollTo(0, 0);
    readHash();
    if (S.sel) S.pendingCenter = true;
    wire();
    wireViewport();
    wireTooltip();
    setTab(S.tab);
    const ok = await T.load();
    if (ok) drawTitle();
    let want = params.get('skin');
    if (!SKINS[want]) { try { want = localStorage.getItem(SKIN_KEY); } catch (e) { want = null; } }
    if (!SKINS[want]) want = 'limezu';
    if (!(await setSkin(want, false)) && want !== 'kenney') await setSkin('kenney', false);
    const lz = window.SwarmLimeZu;  // offer LimeZu in the switcher whenever its (gitignored) art is installed
    if (lz && !lz.ready) lz.load().then((ok) => { if (ok) renderSkinSwitch(); });
    await load();
  }

  window.SwarmAlmanac = { state: S, go, refresh: () => load(true) };
  boot();
})();
