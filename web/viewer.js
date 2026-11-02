/* Swarm World viewer.
 *
 * Connects to the spectator stream (ws(s)://<host>/ws/view), keeps a local copy
 * of the world, renders it on a Canvas 2D map and fills the side panel from the
 * stream plus REST (/api/creature/{id}, /api/metrics). With ?demo=1 it loads
 * demo.js, which fakes both the socket and the REST calls in the browser.
 */
(function () {
  'use strict';

  const T = window.SwarmTiles;      // Kenney art + shared helpers; always loaded
  let SK = T;                       // active world skin: LimeZu when present, else Kenney
  const params = new URLSearchParams(location.search);
  const DEMO = params.get('demo') === '1';

  const EVENT_KINDS = ['say', 'voice', 'invent', 'discover', 'craft', 'gather', 'plant', 'tame', 'eat', 'place', 'write', 'program', 'chronicle', 'fail', 'collapse', 'join', 'sleep'];
  const KIND_LABEL = {
    say: 'Speech', craft: 'Craft', discover: 'Discovery', gather: 'Gather', fail: 'Fail', place: 'Place',
    write: 'Write', program: 'Program', collapse: 'Collapse', join: 'Join', sleep: 'Sleep', eat: 'Eat',
    plant: 'Plant', chronicle: 'Chronicle', tame: 'Tame', invent: 'Invention', voice: 'Voice',
  };
  const KIND_ICON = {
    say: 'say', craft: 'craft', discover: 'discover', gather: 'gather', fail: 'fail', place: 'place',
    write: 'write', program: 'program', collapse: 'collapse', join: 'join', sleep: 'sleep', eat: 'eat',
    plant: 'plant', chronicle: 'chronicle', tame: 'tame', invent: 'invent', voice: 'voice',
  };
  const EVENT_CAP = 300;
  const ZOOMS = [1, 1.5, 2, 2.5, 3, 4, 5];
  const DETAIL_POLL_MS = 1000;
  const SANS = getComputedStyle(document.documentElement).getPropertyValue('--sans') || 'sans-serif';

  /* --------------------------------------------------------------- helpers */
  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const ico = (name) => `<span class="ico" style="--ico:var(--ico-${name})"></span>`;
  const setIco = (el, name) => el.style.setProperty('--ico', `var(--ico-${name})`);
  const humanize = (s) => String(s == null ? '' : s).replace(/_/g, ' ');
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

  function setText(el, text) {
    const t = text == null ? '' : String(text);
    if (el.textContent !== t) el.textContent = t;
  }
  function setHTML(el, html) {
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  }
  function fmtNum(v) {
    if (!isNum(v)) return '–';
    const a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
    if (a >= 1e4) return (v / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'k';
    if (Number.isInteger(v)) return v.toLocaleString('en-US');
    return a < 1 ? v.toFixed(2) : v.toFixed(1);
  }
  function itemName(id) {
    if (id == null) return '';
    if (S.items && S.items[id]) return S.items[id];
    const inv = S.inventions.get(id);
    if (inv && inv.name) return inv.name;
    return humanize(String(id).replace(/^inv_/, ''));   // inventions made after we connected
  }
  /** Catalog id for an item given as id or display name ("plant fiber" -> "plant_fiber"). */
  function itemId(x) {
    if (x == null) return null;
    const k = String(x).trim();
    if (S.items && S.items[k]) return k;
    const low = k.toLowerCase();
    if (S.inventions.has(k)) return k;
    if (S.invByName.has(low)) return S.invByName.get(low);
    for (const [id, name] of Object.entries(S.items || {})) if (String(name).toLowerCase() === low) return id;
    return low.replace(/\s+/g, '_');
  }
  function itemIcon(x, px) {
    const id = itemId(x);
    // inventions (inv_*) and anything the catalog doesn't know get the generic invention icon
    const style = SK.iconStyle(id, px || 20) ||
      (id && (id.startsWith('inv_') || !(S.items && S.items[id])) ? SK.iconStyle('_invention', px || 20) : null);
    return style ? `<span class="item-ico" style="${style};width:${px || 20}px;height:${px || 20}px"></span>` : '';
  }

  /* ----------------------------------------------------------------- state */
  const S = {
    loaded: false,
    width: 64, height: 64, tiles: [], terrain: null,
    objects: new Map(), lit: [], objAt: new Map(), objAnim: new Map(),
    inventions: new Map(), invByName: new Map(),
    voice: { open: false, target: null, radius: 6, disabled: false, busy: false, pulse: 0 },
    cres: new Map(),               // id -> { d: Cre, fx, fy, tx, ty, rx, ry, face }
    nameToId: new Map(),
    items: {},
    tick: 0, clock: { day: 1, phase: 'day', light: 1 },
    tickAt: performance.now(), tickMs: 500, lastTickWall: 0,
    events: [], kindCounts: {}, filters: new Set(EVENT_KINDS), unread: 0,
    metrics: null,
    selected: null, following: false,
    detail: null, detailAt: 0, detailErr: null,
    cam: { x: 32, y: 32 },
    zoom: { level: 2, view: 2, anchor: null },
    tab: 'creature',
    hoverPx: null,
  };
  EVENT_KINDS.forEach((k) => { S.kindCounts[k] = 0; });

  /* ============================================================ connection */
  let ws = null;
  let retry = 0;
  let retryTimer = null;
  let retryAt = 0;
  let lastMsgAt = 0;
  let connState = 'connecting';

  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws/view`;
  }

  function connect() {
    clearTimeout(retryTimer);
    retryTimer = null;
    setConn('connecting');
    let sock;
    try {
      sock = DEMO ? window.SwarmDemo.createSocket() : new WebSocket(wsUrl());
    } catch (err) {
      console.warn('[viewer] cannot open socket', err);
      scheduleReconnect();
      return;
    }
    ws = sock;
    sock.onopen = () => {
      if (ws !== sock) return;
      retry = 0;
      lastMsgAt = performance.now();
      setConn(DEMO ? 'demo' : 'live');
    };
    sock.onmessage = (e) => {
      if (ws !== sock) return;
      let msg;
      try { msg = JSON.parse(e.data); } catch (err) { console.warn('[viewer] non-JSON message ignored'); return; }
      try { onMessage(msg); } catch (err) { console.error('[viewer] failed to apply message', msg && msg.type, err); }
    };
    sock.onclose = () => {
      if (ws !== sock) return;
      ws = null;
      setConn('offline');
      scheduleReconnect();
    };
    sock.onerror = () => { /* a close event follows */ };
  }

  function scheduleReconnect() {
    const steps = [500, 1000, 2000, 4000, 8000, 15000];
    const d = steps[Math.min(retry, steps.length - 1)] * (0.85 + Math.random() * 0.3);
    retry++;
    retryAt = performance.now() + d;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, d);
    renderConn();
  }

  function retryNow() {
    if (connState !== 'offline') return;
    retry = 0;
    connect();
  }

  function setConn(state) {
    connState = state;
    renderConn();
  }

  function renderConn() {
    const el = $('conn');
    const now = performance.now();
    let state = connState;
    let label;
    if (state === 'live' || state === 'demo') {
      const quiet = now - lastMsgAt;
      if (quiet > 5000) { state = 'stalled'; label = `No ticks for ${Math.round(quiet / 1000)}s`; }
      else label = state === 'demo' ? 'Demo world' : 'Live';
    } else if (state === 'connecting') {
      label = 'Connecting…';
    } else {
      const s = Math.max(0, Math.ceil((retryAt - now) / 1000));
      label = s > 0 ? `Offline · retrying in ${s}s` : 'Offline · retrying…';
    }
    el.dataset.state = state;
    el.title = state === 'offline' ? 'Click to retry now' : (DEMO ? 'Fake world generated in the browser' : wsUrl());
    el.style.cursor = state === 'offline' ? 'pointer' : '';
    setText($('conn-label'), label);
    renderVeil();
  }

  function renderVeil() {
    const veil = $('veil');
    if (S.loaded) { veil.classList.add('is-gone'); return; }
    veil.classList.remove('is-gone');
    if (connState === 'offline') {
      const s = Math.max(0, Math.ceil((retryAt - performance.now()) / 1000));
      setText($('veil-title'), 'Can’t reach the world server');
      $('veil-sub').innerHTML = `Is it running? Start it with <span class="mono">python -m swarmworld.server</span>. ` +
        `Retrying in ${s}s. To preview without a server, open <a class="mono" href="?demo=1" style="color:inherit">?demo=1</a>.`;
    } else {
      setText($('veil-title'), DEMO ? 'Building a demo world…' : 'Connecting to the world…');
      $('veil-sub').innerHTML = DEMO ? 'Everything here is generated in your browser.'
        : `Waiting for the world server at <span class="mono">${esc(location.host || 'this page’s host')}</span>`;
    }
  }

  async function apiPost(path, body) {
    if (DEMO) return window.SwarmDemo.post(path, body);
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) { const err = new Error(`HTTP ${r.status}`); err.status = r.status; throw err; }
    return r.json();
  }

  async function api(path) {
    if (DEMO) return window.SwarmDemo.api(path);
    const r = await fetch(path, { cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  /* ============================================================== messages */
  function onMessage(msg) {
    lastMsgAt = performance.now();
    if (connState === 'connecting') setConn(DEMO ? 'demo' : 'live');
    switch (msg.type) {
      case 'init': applyInit(msg); break;
      case 'tick': applyTick(msg); break;
      case 'metrics': applyMetrics(msg); break;
      default: break;
    }
  }

  function applyInit(m) {
    const first = !S.loaded;
    S.width = (m.width | 0) || 64;
    S.height = (m.height | 0) || 64;
    S.tiles = Array.isArray(m.tiles) ? m.tiles : [];
    S.terrain = SK.renderTerrain(S.tiles, S.width, S.height);
    S.objects = new Map();
    for (const o of m.objects || []) S.objects.set(o.id, o);
    indexObjects();
    const now = performance.now();
    const old = S.cres;
    S.cres = new Map();
    for (const c of m.creatures || []) {
      const prev = old.get(c.id);
      S.cres.set(c.id, { d: c, fx: c.x, fy: c.y, tx: c.x, ty: c.y, rx: c.x, ry: c.y, face: prev ? prev.face : 0 });
    }
    indexNames();
    S.items = m.items || {};
    S.tick = m.tick | 0;
    if (m.clock) S.clock = m.clock;
    S.tickAt = now;
    S.loaded = true;

    if (first) {
      S.cam.x = S.width / 2;
      S.cam.y = S.height / 2;
      const fit = Math.min(vw / (S.width * 16), vh / (S.height * 16));
      const level = vw < 700 ? 1.5 : 2;
      S.zoom.level = S.zoom.view = Math.max(level, ZOOMS.find((z) => z >= fit) || 1);
      updateZoomLabel();
      api('/api/metrics').then(applyMetrics).catch(() => {});
      fetchChronicle();
      fetchInventions();
    }
    if (S.selected && !S.cres.has(S.selected)) deselect();
    renderVeil();
    renderHeader();
    renderCreaturePanel();
  }

  function applyTick(m) {
    if (!S.loaded) return;
    const now = performance.now();
    if (S.lastTickWall) {
      const dt = now - S.lastTickWall;
      if (dt > 80 && dt < 3000) S.tickMs = S.tickMs * 0.8 + dt * 0.2;
    }
    S.lastTickWall = now;

    let namesChanged = false;
    for (const c of m.creatures || []) {
      const e = S.cres.get(c.id);
      if (!e) {
        S.cres.set(c.id, { d: c, fx: c.x, fy: c.y, tx: c.x, ty: c.y, rx: c.x, ry: c.y, face: 0 });
        namesChanged = true;
        continue;
      }
      const p = lerpPos(e, now);
      const jump = Math.abs(c.x - p.x) > 2.5 || Math.abs(c.y - p.y) > 2.5;
      e.fx = jump ? c.x : p.x;
      e.fy = jump ? c.y : p.y;
      e.tx = c.x;
      e.ty = c.y;
      if (c.x !== e.d.x) e.face = c.x < e.d.x ? -1 : 1;
      const mx = c.x - e.d.x, my = c.y - e.d.y;
      if (!jump && (mx || my)) e.dir = Math.abs(mx) >= Math.abs(my) ? (mx > 0 ? 'right' : 'left') : (my > 0 ? 'down' : 'up');
      if (c.name !== e.d.name) namesChanged = true;
      e.d = c;
    }
    if (namesChanged) indexNames();

    // Objects can move too (farm animals): interpolate them like creatures.
    let objChanged = false;
    for (const o of m.objects_upsert || []) {
      const prev = S.objects.get(o.id);
      if (prev && (prev.x !== o.x || prev.y !== o.y)) {
        const cur = objPos(prev, now);
        const a = S.objAnim.get(o.id);
        const jump = Math.abs(o.x - cur.x) > 2.5 || Math.abs(o.y - cur.y) > 2.5;
        const mx = o.x - prev.x, my = o.y - prev.y;
        S.objAnim.set(o.id, {
          fx: jump ? o.x : cur.x, fy: jump ? o.y : cur.y, tx: o.x, ty: o.y,
          dir: Math.abs(mx) >= Math.abs(my) ? (mx > 0 ? 'right' : 'left') : (my > 0 ? 'down' : 'up'),
        });
        if (a && jump) S.objAnim.get(o.id).dir = a.dir;
      }
      S.objects.set(o.id, o);
      objChanged = true;
    }
    for (const id of m.objects_removed || []) {
      S.objAnim.delete(id);
      if (S.objects.delete(id)) objChanged = true;
    }
    if (objChanged) indexObjects();
    S.tickAt = now;

    if (isNum(m.tick)) S.tick = m.tick;
    if (m.clock) S.clock = m.clock;

    pushEvents(m.events);
    renderHeader();
    if (S.selected) renderCreaturePanel();
    else if (S.tab === 'creature' && S.tick % 4 === 0) renderRoster();
  }

  function applyMetrics(m) {
    if (!m || typeof m !== 'object') return;
    S.metrics = m;
    if (S.tab === 'swarm') renderSwarm();
  }

  function indexObjects() {
    S.lit = [];
    S.objAt = new Map();
    for (const o of S.objects.values()) {
      if (o.lit) S.lit.push(o);
      const k = o.x + ',' + o.y;
      const arr = S.objAt.get(k);
      if (arr) arr.push(o); else S.objAt.set(k, [o]);
    }
  }

  function indexNames() {
    S.nameToId = new Map();
    for (const [id, e] of S.cres) if (e.d.name) S.nameToId.set(String(e.d.name).toLowerCase(), id);
  }

  /** Resolves an event actor (creature id or name) to display info. */
  function actorInfo(actor) {
    if (actor == null || actor === '') return null;
    let id = S.cres.has(actor) ? actor : S.nameToId.get(String(actor).toLowerCase());
    const e = id ? S.cres.get(id) : null;
    if (!e) return { id: null, name: String(actor), color: null };
    return { id, name: e.d.name || String(actor), color: T.readable(e.d.color || '#cfc6b8') };
  }

  /** Current drawn position of an object (moving objects are interpolated). */
  function objPos(o, now) {
    const a = S.objAnim.get(o.id);
    if (!a) return { x: o.x, y: o.y, moving: false, dir: 'down' };
    const t = clamp((now - S.tickAt) / S.tickMs, 0, 1);
    return { x: a.fx + (a.tx - a.fx) * t, y: a.fy + (a.ty - a.fy) * t, moving: t < 1 && (a.fx !== a.tx || a.fy !== a.ty), dir: a.dir };
  }

  function lerpPos(e, now) {
    const t = clamp((now - S.tickAt) / S.tickMs, 0, 1);
    return { x: e.fx + (e.tx - e.fx) * t, y: e.fy + (e.ty - e.fy) * t, t };
  }

  /* ================================================================ header */
  function renderHeader() {
    const c = S.clock || {};
    setText($('h-day'), `Day ${c.day != null ? c.day : '–'}`);
    const phase = c.phase || '–';
    const PHASE_LABEL = { dawn: 'dawn', day: 'daylight', dusk: 'dusk', night: 'night' };
    const ph = $('h-phase');
    setText(ph, c.phase ? '· ' + (PHASE_LABEL[phase] || phase) : '');
    ph.dataset.phase = phase;
    const pi = $('h-phase-ico');
    pi.dataset.phase = phase;
    setIco(pi, phase === 'night' ? 'night' : 'sun');
    setText($('h-tick'), `tick ${fmtNum(S.tick)}`);
    let awake = 0, asleep = 0;
    for (const e of S.cres.values()) { if (e.d.asleep) asleep++; else awake++; }
    setText($('h-pop'), String(awake + asleep));
    setText($('h-awake'), String(awake));
    setText($('h-asleep'), String(asleep));
  }

  /* ================================================================ events */
  function speechOf(text, name) {
    let s = String(text == null ? '' : text).trim();
    if (name) {
      const re = new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s+(says|said|say|shouts|whispers|asks|tells[^:]*)\\s*:?\\s*', 'i');
      s = s.replace(re, '');
    }
    s = s.replace(/^["“'‘]([\s\S]*)["”'’]$/, '$1');
    return s;
  }

  function eventRow(ev) {
    const li = document.createElement('li');
    const kind = String(ev.kind || 'event');
    li.className = 'ev';
    li.dataset.kind = kind;
    const who = actorInfo(ev.actor);
    const whoHtml = who ? `<span class="who"${who.color ? ` style="color:${who.color}"` : ''}>${esc(who.name)}</span>` : '';
    const text = String(ev.text == null ? '' : ev.text);
    let body;
    if (kind === 'chronicle') {
      const excerpt = text.replace(/^chronicle,?\s*/i, '');
      li.innerHTML = `${ico('chronicle')}<div><span class="tag">Chronicle</span><span class="chron-ex">${esc(excerpt.length > 160 ? excerpt.slice(0, 159) + '…' : excerpt)}</span></div>` +
        `<span class="t num">${esc(ev.tick != null ? ev.tick : '')}</span>`;
      li.classList.add('has-target');
      li.dataset.chron = '1';
      li.title = 'Read the chronicle';
      return li;
    }
    if (kind === 'voice') {
      const words = text.replace(/^a voice from the sky\s*:?\s*/i, '').replace(/^["“]([\s\S]*)["”]$/, '$1');
      body = `<span class="tag">Voice from the sky</span><span class="q">“${esc(words)}”</span>`;
    } else if (kind === 'say') {
      body = `<span class="line">${whoHtml}<span class="q">“${esc(speechOf(text, who && who.name))}”</span></span>`;
    } else {
      const startsWithName = who && text.toLowerCase().startsWith(who.name.toLowerCase());
      const tag = kind === 'discover' ? '<span class="tag">Discovery</span>' : kind === 'invent' ? '<span class="tag">Invention</span>' : '';
      let safe = esc(text || KIND_LABEL[kind] || kind);
      // set the creature's own description ("…") apart in an invention announcement
      if (kind === 'invent') safe = safe.replace(/(“[^”]*”|&quot;.*?&quot;)/, '<span class="inv-desc">$1</span>');
      body = `${tag}${startsWithName ? '' : whoHtml}${safe}`;
    }
    let lead = ico(KIND_ICON[kind] || 'dot');
    if (kind === 'invent') {
      const m = text.match(/invented (?:the |a |an )?(.+?)!/i);
      if (m) {
        li.dataset.inv = m[1];
        lead = itemIcon(m[1], 20) || lead;
      }
    }
    li.innerHTML = `${lead}<div>${body}</div><span class="t num" title="Tick ${esc(ev.tick)}">${esc(ev.tick != null ? ev.tick : '')}</span>`;
    if ((who && who.id) || (isNum(ev.x) && isNum(ev.y))) {
      li.classList.add('has-target');
      if (who && who.id) li.dataset.actor = who.id;
      if (isNum(ev.x)) { li.dataset.x = ev.x; li.dataset.y = ev.y; }
      li.title = who && who.id ? `Follow ${who.name} on the map` : 'Show on the map';
    }
    return li;
  }

  function pushEvents(evs) {
    if (!Array.isArray(evs) || !evs.length) return;
    const feed = $('feed');
    for (const ev of evs) {
      if (!ev) continue;
      S.events.unshift(ev);
      if (ev.kind in S.kindCounts) S.kindCounts[ev.kind]++;
      const li = eventRow(ev);
      li.classList.add('is-new');
      feed.insertBefore(li, feed.firstChild);
    }
    while (S.events.length > EVENT_CAP) {
      const gone = S.events.pop();
      if (gone && gone.kind in S.kindCounts) S.kindCounts[gone.kind]--;
      if (feed.lastChild) feed.lastChild.remove();
    }
    // clear the arrival flash on older rows so it never replays
    const rows = feed.children;
    for (let i = evs.length; i < Math.min(rows.length, evs.length + 40); i++) rows[i].classList.remove('is-new');
    $('feed-empty').hidden = S.events.length > 0;
    renderFilterCounts();
    if (evs.some((ev) => ev && ev.kind === 'invent')) fetchInventions();
    if (evs.some((ev) => ev && ev.kind === 'voice')) S.voice.pulse = performance.now();
    if (evs.some((ev) => ev && ev.kind === 'chronicle')) {
      fetchChronicle();
      if (S.tab !== 'chronicle') $('chron-dot').hidden = false;
    }
    if (S.tab !== 'events') {
      S.unread += evs.length;
      const b = $('ev-unread');
      b.hidden = false;
      setText(b, S.unread > 99 ? '99+' : String(S.unread));
    }
  }

  function buildFilters() {
    const box = $('ev-filters');
    const html = EVENT_KINDS.map((k) =>
      `<button type="button" class="fchip" data-kind="${k}" aria-pressed="true" title="Show or hide ${KIND_LABEL[k].toLowerCase()} events (Alt-click: only these)">` +
      `${ico(KIND_ICON[k])}<span>${KIND_LABEL[k]}</span><span class="n num" data-n="${k}">0</span></button>`).join('') +
      '<button type="button" class="fchip all" data-all="1" title="Show every kind">Show all</button>';
    box.innerHTML = html;
    box.addEventListener('click', (e) => {
      const b = e.target.closest('.fchip');
      if (!b) return;
      if (b.dataset.all) { EVENT_KINDS.forEach((k) => S.filters.add(k)); }
      else {
        const k = b.dataset.kind;
        if (e.altKey || e.metaKey) { S.filters.clear(); S.filters.add(k); }
        else if (S.filters.has(k)) S.filters.delete(k); else S.filters.add(k);
      }
      applyFilters();
    });
  }

  function applyFilters() {
    const feed = $('feed');
    for (const k of EVENT_KINDS) feed.classList.toggle('hide-' + k, !S.filters.has(k));
    for (const b of $('ev-filters').querySelectorAll('.fchip[data-kind]')) b.setAttribute('aria-pressed', String(S.filters.has(b.dataset.kind)));
  }

  function renderFilterCounts() {
    for (const k of EVENT_KINDS) {
      const n = $('ev-filters').querySelector(`[data-n="${k}"]`);
      if (n) setText(n, String(S.kindCounts[k] || 0));
    }
  }

  /* ============================================================== creature */
  function activityText(c) {
    if (!c) return '';
    const a = c.activity;
    if (a == null || a === '') return 'idle';
    if (typeof a === 'string') return humanize(a);
    if (typeof a === 'object') {
      const verb = a.kind || a.action || a.type || a.name || 'busy';
      const tgt = a.target || a.label || '';
      return humanize(verb) + (tgt ? ' ' + humanize(tgt) : '');
    }
    return String(a);
  }

  function select(id, follow) {
    if (!S.cres.has(id)) return;
    const changed = S.selected !== id;
    S.selected = id;
    if (follow) S.following = true;
    if (changed) {
      S.detail = null;
      S.detailErr = null;
      S.detailAt = 0;
      startPolling();
    }
    renderCreaturePanel();
    renderFollow();
  }

  function deselect() {
    S.selected = null;
    S.following = false;
    S.detail = null;
    stopPolling();
    renderCreaturePanel();
    renderFollow();
  }

  let pollTimer = null;
  let pollBusy = false;
  function startPolling() {
    stopPolling();
    pollDetail();
    pollTimer = setInterval(pollDetail, DETAIL_POLL_MS);
  }
  function stopPolling() { clearInterval(pollTimer); pollTimer = null; }
  async function pollDetail() {
    const id = S.selected;
    if (!id) return;
    if (pollBusy || document.hidden) { renderDetailFoot(); return; }
    pollBusy = true;
    try {
      const d = await api('/api/creature/' + encodeURIComponent(id));
      if (S.selected === id) {
        S.detail = d;
        S.detailAt = Date.now();
        S.detailErr = null;
        renderCreaturePanel();
      }
    } catch (err) {
      if (S.selected === id) { S.detailErr = (err && err.message) || String(err); renderDetailFoot(); }
    } finally {
      pollBusy = false;
    }
  }

  function renderDetailFoot() {
    const foot = $('cre-foot');
    if (!S.selected) return;
    if (S.detailErr) {
      foot.classList.add('is-error');
      setText(foot, `Couldn’t load details (${S.detailErr}). Retrying every second.`);
    } else if (!S.detailAt) {
      foot.classList.remove('is-error');
      setText(foot, 'Loading details…');
    } else {
      foot.classList.remove('is-error');
      const s = Math.round((Date.now() - S.detailAt) / 1000);
      setText(foot, s <= 1 ? 'Details refresh every second.' : `Details last updated ${s}s ago.`);
    }
  }

  let portraitKey = '';
  function renderCreaturePanel() {
    const id = S.selected;
    $('cre-empty').hidden = !!id;
    $('cre').hidden = !id;
    if (!id) { renderRoster(); return; }

    const e = S.cres.get(id);
    const live = e ? e.d : {};
    const d = S.detail && (S.detail.id == null || S.detail.id === id) ? S.detail : {};
    const name = live.name || d.name || id;
    const color = live.color || '#cfc6b8';
    const model = live.model || d.model || 'unknown model';

    setText($('cre-name'), name);
    const pk = id + '|' + color + '|' + SK.name;
    if (pk !== portraitKey) {
      portraitKey = pk;
      const p = $('cre-portrait');
      p.replaceChildren(SK.creatureBadge({ id, color }, 44));
      p.style.background = `radial-gradient(circle at 50% 60%, ${T.rgba(color, 0.18)}, transparent 70%), var(--ink-1)`;
    }
    const badge = $('cre-model');
    setText(badge, model);
    badge.style.color = T.readable(color);
    badge.style.borderColor = T.rgba(color, 0.45);
    badge.style.background = T.rgba(color, 0.1);

    const st = $('cre-state');
    let stClass = 'cre-state', stHtml;
    if (isNum(live.health) && live.health <= 0) { stClass += ' is-down'; stHtml = 'collapsed'; }
    else if (live.asleep) { stClass += ' is-asleep'; stHtml = 'asleep'; }
    else if (live.thinking) { stClass += ' is-thinking'; stHtml = '<span class="dot"></span>thinking…'; }
    else stHtml = esc(activityText(live));
    if (live.holding) stHtml += ` · holding ${esc(itemName(live.holding))}`;
    st.className = stClass;
    setHTML(st, stHtml);

    // persona: {traits:[..], drive:".."} or a string
    const per = d.persona;
    let perHtml = '';
    if (per && typeof per === 'object') {
      const traits = Array.isArray(per.traits) ? per.traits : [];
      perHtml = traits.map((t) => `<span class="trait">${esc(t)}</span>`).join('');
      if (per.drive) perHtml += `<span class="trait drive"><span>drive</span>${esc(per.drive)}</span>`;
      for (const [k, v] of Object.entries(per)) {
        if (k === 'traits' || k === 'drive' || k === 'name' || v == null || typeof v === 'object') continue;
        perHtml += `<span class="trait"><span style="color:var(--text-3);margin-right:4px">${esc(humanize(k))}</span>${esc(v)}</span>`;
      }
    } else if (per) {
      perHtml = `<p class="persona-text">${esc(per)}</p>`;
    }
    setHTML($('cre-persona'), perHtml);

    for (const k of ['satiety', 'energy', 'health']) {
      const v = isNum(live[k]) ? live[k] : d[k];
      const row = $('cre-needs').querySelector(`[data-need="${k}"]`);
      const pct = isNum(v) ? clamp(v, 0, 100) : 0;
      row.querySelector('.bar-fill').style.transform = `scaleX(${pct / 100})`;
      setText(row.querySelector('.need-val'), isNum(v) ? String(Math.round(v)) : '–');
      row.classList.toggle('is-low', isNum(v) && v < 25);
    }

    emptyable($('cre-goal'), d.goal, 'No goal yet.');
    emptyable($('cre-thought'), d.last_thought, S.detailAt ? 'No thoughts yet.' : '…');
    setHTML($('cre-intent'), intentionHtml(d.last_intention));
    const res = $('cre-result');
    const r = d.last_result;
    let rText = '', rClass = 'result';
    if (r && typeof r === 'object') {
      rText = r.message || r.text || JSON.stringify(r);
      if (r.ok === true) rClass += ' ok'; else if (r.ok === false) rClass += ' fail';
    } else if (r) rText = String(r);
    res.className = rClass;
    setText(res, rText);

    emptyable($('cre-senses'), d.perception, S.detailAt ? 'Nothing sensed yet.' : 'Loading…');

    // inventory {name:n} (or a list)
    const inv = d.inventory;
    let invHtml = '';
    if (inv && typeof inv === 'object') {
      const entries = Array.isArray(inv) ? inv.map((x) => [x, 1]) : Object.entries(inv);
      invHtml = entries.filter(([, n]) => n).map(([k, n]) =>
        `<span class="chip">${itemIcon(k)}${esc(itemName(k))}${n > 1 ? `<span class="n">×${esc(n)}</span>` : ''}</span>`).join('');
    }
    setHTML($('cre-inv'), invHtml || '<span class="is-empty">Empty-handed.</span>');

    const rec = Array.isArray(d.known_recipes) ? d.known_recipes : [];
    setHTML($('cre-recipes'), rec.length
      ? rec.map(recipeHtml).join('')
      : '<span class="is-empty">No recipes known.</span>');

    setHTML($('cre-people'), peopleHtml(d.people));
    emptyable($('cre-summary'), d.summary, 'It hasn’t reflected on its life yet.');

    const recent = Array.isArray(d.recent) ? d.recent : [];
    setHTML($('cre-recent'), recent.length
      ? recent.map((x) => `<li>${esc(typeof x === 'object' ? (x.text || JSON.stringify(x)) : x)}</li>`).join('')
      : '<li class="is-empty" style="padding-left:0">No memories yet.</li>');

    const stats = d.stats && typeof d.stats === 'object' ? Object.entries(d.stats) : [];
    $('cre-stats-block').hidden = !stats.length;
    setHTML($('cre-stats'), stats.map(([k, v]) =>
      `<dt>${esc(humanize(k))}</dt><dd>${esc(isNum(v) ? fmtNum(v) : (typeof v === 'object' ? JSON.stringify(v) : v))}</dd>`).join(''));

    renderDetailFoot();
  }

  function emptyable(el, value, emptyText) {
    const has = value != null && String(value).trim() !== '';
    el.classList.toggle('is-empty', !has);
    setText(el, has ? value : emptyText);
  }

  /** "3 stick + 2 stone -> campfire", an id, or {output, inputs} -> a row with the output's icon. */
  function recipeHtml(x) {
    let out, inputs = '';
    if (x && typeof x === 'object') {
      out = x.output || x.id || x.name;
      if (x.inputs && typeof x.inputs === 'object') inputs = Object.entries(x.inputs).map(([k, n]) => `${n} ${itemName(k)}`).join(' + ');
    } else {
      const str = String(x);
      const m = str.match(/^(.*?)\s*(?:->|→|=>)\s*(.+)$/);
      if (m) { inputs = m[1]; out = m[2]; } else out = str;
    }
    let name = String(out).replace(/^\d+\s*x?\s+/, '');
    // "stone hammer (near a campfire)": the station note is not part of the name
    const where = name.match(/\s*\(([^)]*)\)\s*$/);
    if (where) name = name.slice(0, where.index);
    const note = [inputs, where ? where[1] : ''].filter(Boolean).join(' · ');
    return `<span class="recipe-row">${itemIcon(name, 20) || '<span class="item-ico none"></span>'}` +
      `<b>${esc(itemName(itemId(name)) || name)}</b>${note ? `<span class="r-in">${esc(note)}</span>` : ''}</span>`;
  }

  function intentionHtml(it) {
    if (it == null || it === '') return '';
    if (typeof it === 'string') {
      try { it = JSON.parse(it); } catch (e) {
        const m = it.trim().match(/^([a-z_]+)\s*(.*)$/i);
        return m ? `<span class="verb">${esc(m[1])}</span>${m[2] ? `<span class="tgt">${esc(m[2])}</span>` : ''}` : `<span class="tgt">${esc(it)}</span>`;
      }
    }
    if (typeof it !== 'object') return esc(it);
    const parts = [`<span class="verb">${esc(it.action || '?')}</span>`];
    if (it.target) parts.push(`<span class="arrow">→</span><span class="tgt">${esc(it.target)}</span>`);
    if (Array.isArray(it.items) && it.items.length) parts.push(`<span>[${esc(it.items.join(', '))}]</span>`);
    if (isNum(it.count) && it.count > 1) parts.push(`<span>×${esc(it.count)}</span>`);
    if (it.text) parts.push(`<span class="say">“${esc(String(it.text).slice(0, 220))}${String(it.text).length > 220 ? '…' : ''}”</span>`);
    return parts.join(' ');
  }

  function peopleHtml(p) {
    let rows = [];
    if (Array.isArray(p)) {
      rows = p.map((x) => {
        if (Array.isArray(x)) return [x[0], x[1]];
        if (x && typeof x === 'object') return [x.name || x.id, x.note || x.text || x.opinion || x.relation || ''];
        const s = String(x);
        const m = s.match(/^([^:—–-]{1,40}?)\s*[:—–-]\s+(.+)$/);
        return m ? [m[1], m[2]] : [s, ''];
      });
    } else if (p && typeof p === 'object') {
      rows = Object.entries(p);
    }
    if (!rows.length) return '<li class="is-empty">Hasn’t met anyone yet.</li>';
    return rows.map(([n, note]) => {
      const who = actorInfo(n);
      const style = who && who.color ? ` style="color:${who.color}"` : '';
      return `<li><b${style}>${esc(who ? who.name : n)}</b>${esc(note || '')}</li>`;
    }).join('');
  }

  const badgeCache = new Map();
  function badgeURL(id, color) {
    const k = id + '|' + color + '|' + SK.name;
    let u = badgeCache.get(k);
    if (!u) { u = SK.creatureBadge({ id, color }, 28).toDataURL(); badgeCache.set(k, u); }
    return u;
  }

  function renderRoster() {
    const list = [...S.cres.values()].map((e) => e.d);
    list.sort((a, b) => (a.asleep - b.asleep) || String(a.name).localeCompare(String(b.name)));
    const html = list.map((c) => {
      const state = c.asleep ? 'asleep' : c.thinking ? 'thinking…' : activityText(c);
      return `<li><button type="button" data-id="${esc(c.id)}">` +
        `<img src="${badgeURL(c.id, c.color || '#cfc6b8')}" width="28" height="28" alt="" style="image-rendering:pixelated">` +
        `<span><span class="r-name" style="color:${T.readable(c.color || '#cfc6b8')}">${esc(c.name || c.id)}</span><span class="r-act">${esc(state)}</span></span>` +
        `<span class="r-model">${esc(c.model || '')}</span></button></li>`;
    }).join('');
    setHTML($('roster'), html || '<li class="empty-sub" style="padding:10px 0">No creatures yet. They appear when a brain node joins.</li>');
  }

  /* ================================================================= swarm */
  const METRIC_ORDER = ['creatures', 'awake', 'thinks', 'success_rate', 'act_ok', 'act_fail', 'parse_failures', 'errors', 'loops',
    'avg_latency_s', 'avg_latency_ms', 'tokens_in', 'tokens_out', 'cache_hit', 'speech', 'gathered', 'crafted', 'built',
    'discoveries', 'inventions', 'unique_items', 'writing', 'programs', 'collapses'];
  const METRIC_LABEL = {
    creatures: 'Creatures', awake: 'Awake', thinks: 'Thinks', success_rate: 'Success', act_ok: 'OK', act_fail: 'Failed',
    parse_failures: 'Parse err', errors: 'Errors', loops: 'Loops', avg_latency_s: 'Latency', avg_latency_ms: 'Latency',
    tokens_in: 'Tok in', tokens_out: 'Tok out', cache_hit: 'Cache hit', speech: 'Speech', gathered: 'Gathered',
    crafted: 'Crafted', built: 'Built', discoveries: 'Discov.', unique_items: 'Items', writing: 'Writing',
    programs: 'Programs', collapses: 'Collapses', inventions: 'Invent.',
  };
  function fmtMetric(k, x) {
    if (!isNum(x)) return '–';
    if (k.endsWith('_ms')) return `${Math.round(x).toLocaleString('en-US')} ms`;
    if (k.endsWith('_s')) return `${x.toFixed(1)} s`;
    if (k.endsWith('_rate') || k === 'cache_hit') return `${Math.round(x * 100)}%`;
    return fmtNum(x);
  }

  function modelColor(tag) {
    for (const e of S.cres.values()) if (e.d.model === tag && e.d.color) return e.d.color;
    return '#8f8393';
  }

  function renderSwarm() {
    const m = S.metrics || {};
    setText($('sw-tpm'), isNum(m.thinks_per_min) ? m.thinks_per_min.toFixed(1) : '–');

    const models = m.models && typeof m.models === 'object' ? Object.entries(m.models) : [];
    const cols = new Set();
    for (const [, v] of models) {
      if (!v || typeof v !== 'object') continue;
      for (const [k, x] of Object.entries(v)) if (isNum(x) || Array.isArray(x)) cols.add(k);
    }
    const ordered = METRIC_ORDER.filter((k) => cols.has(k)).concat([...cols].filter((k) => !METRIC_ORDER.includes(k)).sort());
    $('sw-empty').hidden = models.length > 0;
    let html = '';
    if (models.length) {
      html = '<thead><tr><th class="m" scope="col">Model</th>' +
        ordered.map((k) => `<th scope="col" title="${esc(k)}">${esc(METRIC_LABEL[k] || humanize(k))}</th>`).join('') + '</tr></thead><tbody>' +
        models.map(([tag, v]) => {
          const row = v && typeof v === 'object' ? v : {};
          return `<tr><td class="m" title="${esc(tag)}"><i style="background:${esc(modelColor(tag))}"></i>${esc(tag)}</td>` +
            ordered.map((k) => {
              let x = row[k];
              if (Array.isArray(x)) x = x.length;
              const txt = fmtMetric(k, x);
              return `<td class="${x === 0 || !isNum(x) ? 'zero' : ''}">${esc(txt)}</td>`;
            }).join('') + '</tr>';
        }).join('') + '</tbody>';
    }
    setHTML($('sw-table'), html);
    $('sw-table-wrap').hidden = !models.length;
    const wrap = $('sw-table-wrap');
    $('sw-note').hidden = !models.length || wrap.scrollWidth <= wrap.clientWidth + 2;

    const disc = Array.isArray(m.discoveries) ? m.discoveries.slice() : [];
    disc.sort((a, b) => (b.tick || 0) - (a.tick || 0));
    $('sw-disc-empty').hidden = disc.length > 0;
    setHTML($('sw-disc'), disc.map((x) => {
      const who = actorInfo(x.by);
      const style = who && who.color ? ` style="color:${who.color}"` : '';
      return `<li${x.invented ? ' class="invented"' : ''}>${itemIcon(x.item, 20) || ico('discover')}<span><span class="item">${esc(itemName(x.item))}</span> — ${x.invented ? 'invented by' : 'first by'} <span class="by"${style}>${esc(who ? who.name : (x.by || 'someone'))}</span></span>` +
        `<span class="t num">tick ${esc(fmtNum(x.tick))}</span></li>`;
    }).join(''));
  }

  /* ================================================================== tabs */
  function showTab(name) {
    S.tab = name;
    for (const b of document.querySelectorAll('.tab')) b.setAttribute('aria-selected', String(b.dataset.tab === name));
    for (const p of document.querySelectorAll('.tabpane')) p.hidden = p.id !== 'tab-' + name;
    if (name === 'events') { S.unread = 0; $('ev-unread').hidden = true; }
    if (name === 'swarm') renderSwarm();
    if (name === 'creature') renderCreaturePanel();
    if (name === 'chronicle') {
      $('chron-dot').hidden = true;
      if (!chron.loaded) fetchChronicle();
      renderChronicle(true);
    }
  }

  /* ============================================================ inventions */
  let invBusy = false, invAt = 0;
  async function fetchInventions() {
    if (invBusy) return;
    invBusy = true;
    try {
      const d = await api('/api/inventions');
      const list = Array.isArray(d) ? d : (d && Array.isArray(d.inventions) ? d.inventions : []);
      S.inventions = new Map();
      S.invByName = new Map();
      for (const inv of list) {
        if (!inv || !inv.id) continue;
        S.inventions.set(inv.id, inv);
        if (inv.name) S.invByName.set(String(inv.name).toLowerCase(), inv.id);
      }
      if (SK.setInventions) SK.setInventions(list);
      // everything that shows an item icon picks up the composed icons
      for (const li of document.querySelectorAll('.ev[data-kind="invent"][data-inv]')) {
        const icon = itemIcon(li.dataset.inv, 20);
        const old = li.firstElementChild;
        if (icon && old && !old.classList.contains('item-ico')) old.outerHTML = icon;
      }
      if (S.selected) renderCreaturePanel();
      if (S.tab === 'swarm') renderSwarm();
    } catch (err) {
      // older servers have no /api/inventions; inventions keep the generic icon
    } finally {
      invBusy = false;
      invAt = performance.now();
    }
  }

  /* ============================================================= chronicle */
  const chron = { list: [], loaded: false, err: null, busy: false };

  async function fetchChronicle() {
    if (chron.busy) return;
    chron.busy = true;
    try {
      const d = await api('/api/chronicle');
      chron.list = Array.isArray(d) ? d : (d && Array.isArray(d.chapters) ? d.chapters : []);
      chron.err = null;
    } catch (err) {
      chron.err = (err && err.message) || String(err);
    } finally {
      chron.busy = false;
      chron.loaded = true;
    }
    renderChronicle(false);
  }

  function chapterParas(text) {
    const t = String(text || '').replace(/^chronicle,?\s*day\s*\d+\s*:\s*/i, '').trim();
    return t.split(/\n\s*\n|\n/).filter((x) => x.trim()).map((x) => `<p>${esc(x.trim())}</p>`).join('');
  }

  /** Newest chapter at the bottom; follows new chapters unless the reader has scrolled up. */
  function renderChronicle(opening) {
    const pane = $('tab-chronicle');
    const box = $('chron');
    const nearBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80;
    const html = chron.list.map((ch) => {
      const phase = ch.phase ? `<span class="ph">${esc(ch.phase)}</span>` : '';
      return `<article class="chapter"><header><h3>Day ${esc(ch.day != null ? ch.day : '?')}${phase}</h3>` +
        `<span class="t num">tick ${esc(fmtNum(ch.tick))}</span></header>${chapterParas(ch.text)}</article>`;
    }).join('');
    const changed = box._html !== html;
    setHTML(box, html);
    const empty = $('chron-empty');
    empty.hidden = chron.list.length > 0;
    setText($('chron-empty-text'), chron.err
      ? `The chronicle isn’t available (${chron.err}). It appears once the server writes its first chapter.`
      : chron.loaded ? 'No chapters yet. The world writes one every five minutes of world time.' : 'Loading the chronicle…');
    if (S.tab !== 'chronicle') return;
    if (opening || (changed && nearBottom)) {
      pane.scrollTop = pane.scrollHeight;
      $('chron-jump').hidden = true;
    } else if (changed) {
      $('chron-jump').hidden = false;
    }
  }

  function renderCredit() {
    const foot = $('panel-foot');
    const q = new URLSearchParams(location.search);
    let link = '';
    if (SK.name === 'limezu') {
      q.set('skin', 'kenney');
      link = `<a href="?${esc(q.toString())}">Kenney skin</a>`;
    } else if (params.get('skin') === 'kenney') {
      q.delete('skin');
      link = `<a href="?${esc(q.toString())}">LimeZu skin</a>`;
    }
    const credit = SK.name === 'limezu'
      ? 'Art: <a href="https://limezu.itch.io" target="_blank" rel="noopener" title="World art by LimeZu. UI glyphs: Kenney 1-Bit Pack (CC0).">LimeZu (limezu.itch.io)</a>'
      : 'Art: Kenney 1-Bit Pack (CC0)';
    foot.innerHTML = `<span>${credit}</span>${link ? `<span>${link}</span>` : ''}`;
  }

  function setPanel(open) {
    document.body.classList.toggle('panel-collapsed', !open);
    const b = $('panel-toggle');
    b.setAttribute('aria-expanded', String(open));
    b.title = open ? 'Hide side panel (\\)' : 'Show side panel (\\)';
    setIco(b.querySelector('.ico'), open ? 'right' : 'left');
  }

  function renderFollow() {
    const pill = $('follow-pill');
    const e = S.following && S.selected ? S.cres.get(S.selected) : null;
    pill.hidden = !e;
    if (!e) return;
    setText($('follow-name'), e.d.name || e.d.id);
    $('follow-swatch').style.background = e.d.color || '#cfc6b8';
  }

  /* ================================================================== map */
  const canvas = $('map');
  const ctx = canvas.getContext('2d');
  const night = document.createElement('canvas');
  const nctx = night.getContext('2d');
  let vw = 0, vh = 0, dpr = 1;
  const view = { ox: 0, oy: 0, ts: 32 };
  let lastFrame = performance.now();

  function resize() {
    const r = canvas.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    vw = r.width;
    vh = r.height;
    const w = Math.max(1, Math.round(vw * dpr));
    const h = Math.max(1, Math.round(vh * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w; canvas.height = h;
      night.width = w; night.height = h;
    }
  }

  function clampCam() {
    S.cam.x = clamp(S.cam.x, 0, S.width);
    S.cam.y = clamp(S.cam.y, 0, S.height);
  }

  function setZoom(level, ax, ay) {
    level = clamp(level, ZOOMS[0], ZOOMS[ZOOMS.length - 1]);
    if (level === S.zoom.level) return;
    if (ax == null || S.following) S.zoom.anchor = null;
    else {
      const ts = 16 * S.zoom.view;
      S.zoom.anchor = { sx: ax, sy: ay, wx: S.cam.x + (ax - vw / 2) / ts, wy: S.cam.y + (ay - vh / 2) / ts };
    }
    S.zoom.level = level;
    updateZoomLabel();
  }
  function zoomStep(dir, ax, ay) {
    let i = ZOOMS.indexOf(S.zoom.level);
    if (i < 0) i = ZOOMS.findIndex((z) => z >= S.zoom.level);
    setZoom(ZOOMS[clamp(i + dir, 0, ZOOMS.length - 1)], ax, ay);
  }
  function updateZoomLabel() {
    setText($('zoom-label'), `${S.zoom.level}×`);
    document.querySelector('[data-zoom="-1"]').disabled = S.zoom.level <= ZOOMS[0];
    document.querySelector('[data-zoom="1"]').disabled = S.zoom.level >= ZOOMS[ZOOMS.length - 1];
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - lastFrame) / 1000);
    lastFrame = now;
    if (!vw || !vh) resize();

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = '#0c090f';
    ctx.fillRect(0, 0, vw, vh);
    if (!S.loaded || !S.terrain) return;

    // zoom easing (keeps the point under the cursor fixed)
    const Z = S.zoom;
    if (Z.view !== Z.level) {
      Z.view += (Z.level - Z.view) * (1 - Math.exp(-dt * 16));
      if (Math.abs(Z.level - Z.view) < 0.004) Z.view = Z.level;
      if (Z.anchor) {
        const ts = 16 * Z.view;
        S.cam.x = Z.anchor.wx - (Z.anchor.sx - vw / 2) / ts;
        S.cam.y = Z.anchor.wy - (Z.anchor.sy - vh / 2) / ts;
      }
      if (Z.view === Z.level) Z.anchor = null;
    }

    // creature positions for this frame
    const list = [];
    for (const e of S.cres.values()) {
      const p = lerpPos(e, now);
      e.rx = p.x; e.ry = p.y;
      e.moving = p.t < 1 && (e.fx !== e.tx || e.fy !== e.ty);
      list.push(e);
    }
    // back to front; the selected creature always on top of anyone sharing its tile
    list.sort((a, b) => (a.d.id === S.selected) - (b.d.id === S.selected) || a.ry - b.ry);

    if (S.following && S.selected) {
      const e = S.cres.get(S.selected);
      if (e) {
        const k = 1 - Math.exp(-dt * 7);
        S.cam.x += (e.rx + 0.5 - S.cam.x) * k;
        S.cam.y += (e.ry + 0.5 - S.cam.y) * k;
      }
    }
    clampCam();

    const ts = 16 * Z.view;
    const ox = Math.round(vw / 2 - S.cam.x * ts);
    const oy = Math.round(vh / 2 - S.cam.y * ts);
    view.ox = ox; view.oy = oy; view.ts = ts;
    const x0 = Math.max(0, Math.floor(-ox / ts) - 1);
    const y0 = Math.max(0, Math.floor(-oy / ts) - 1);
    const x1 = Math.min(S.width - 1, Math.ceil((vw - ox) / ts));
    const y1 = Math.min(S.height - 1, Math.ceil((vh - oy) / ts));

    // world edge
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(ox - 6, oy - 6, S.width * ts + 12, S.height * ts + 12);
    ctx.drawImage(S.terrain, ox, oy, S.width * ts, S.height * ts);

    if (SK.drawsWater) {
      for (let y = y0; y <= y1; y++) {
        const row = S.tiles[y];
        if (!row) continue;
        for (let x = x0; x <= x1; x++) {
          const code = row[x];
          if (code === 'w' || code === 'W') SK.drawWater(ctx, code, x, y, ox + x * ts, oy + y * ts, ts, now);
        }
      }
    }

    // Objects and creatures are drawn back to front so tall sprites (trees,
    // two-tile characters) overlap correctly. Sprites can reach a few tiles
    // beyond their own tile, so the culling margin is generous.
    const M = 3;
    const draw = [];
    for (const o of S.objects.values()) {
      if (o.x < x0 - M || o.x > x1 + M || o.y < y0 || o.y > y1 + M) continue;
      const pos = S.objAnim.has(o.id) ? objPos(o, now) : null;
      draw.push({ k: pos ? pos.y + 0.05 : o.y, o, pos });
    }
    for (const e of list) {
      if (e.rx < x0 - M || e.rx > x1 + M || e.ry < y0 || e.ry > y1 + M) continue;
      draw.push({ k: e.ry + 0.1 + (e.d.id === S.selected ? 0.05 : 0), e });
    }
    draw.sort((a, b) => a.k - b.k);
    const p = ts / 16;
    const tamed = [];
    for (const it of draw) {
      if (it.o) {
        const ps = it.pos;
        SK.drawObject(ctx, it.o, ox + (ps ? ps.x : it.o.x) * ts, oy + (ps ? ps.y : it.o.y) * ts, ts, now, ps || undefined);
        if (it.o.tamed_by) tamed.push([ox + (ps ? ps.x : it.o.x) * ts, oy + (ps ? ps.y : it.o.y) * ts, it.o]);
        continue;
      }
      const e = it.e, c = e.d;
      const sx = ox + e.rx * ts, sy = oy + e.ry * ts;
      ctx.fillStyle = 'rgba(0,0,0,0.3)';
      ctx.beginPath();
      ctx.ellipse(sx + ts / 2, sy + ts - 1.5 * p, 5 * p, 1.7 * p, 0, 0, Math.PI * 2);
      ctx.fill();
      const low = isNum(c.health) && c.health < 30;
      SK.drawCreature(ctx, c, sx, sy, ts, {
        dim: low, asleep: !!c.asleep, flip: e.face ? e.face < 0 : undefined,
        dir: e.dir || 'down', moving: e.moving && !c.asleep, t: now,
      });
    }

    drawNight(list, ox, oy, ts, now);
    for (const [hx, hy, o] of tamed) drawHeart(hx + ts / 2, hy + ts - (ANIMAL_TOP[o.kind] || 1) * ts - 2, ts);
    drawVoice(ox, oy, ts, now);
    drawOverlays(list, ox, oy, ts, now);
  }

  /** The area a targeted voice reaches (Chebyshev distance, like hearing), and a sky glow when it speaks. */
  function drawVoice(ox, oy, ts, now) {
    const V = S.voice;
    if (V.open && V.target) {
      const r = V.radius;
      const x = ox + (V.target.x - r) * ts, y = oy + (V.target.y - r) * ts, w = (2 * r + 1) * ts;
      ctx.save();
      ctx.fillStyle = 'rgba(130,200,255,0.10)';
      roundRect(x, y, w, w, ts * 0.8);
      ctx.fill();
      ctx.setLineDash([6, 5]);
      ctx.lineDashOffset = -now / 60;
      ctx.lineWidth = 2;
      ctx.strokeStyle = 'rgba(170,220,255,0.85)';
      roundRect(x + 1, y + 1, w - 2, w - 2, ts * 0.8);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(220,240,255,0.95)';
      ctx.beginPath(); ctx.arc(ox + (V.target.x + 0.5) * ts, oy + (V.target.y + 0.5) * ts, Math.max(3, ts * 0.12), 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }
    const age = now - V.pulse;
    if (V.pulse && age < 2600) {
      const a = Math.sin(Math.min(1, age / 2600) * Math.PI) * 0.35;
      const g = ctx.createRadialGradient(vw / 2, vh * 0.1, 0, vw / 2, vh * 0.1, Math.max(vw, vh));
      g.addColorStop(0, `rgba(190,225,255,${a.toFixed(3)})`);
      g.addColorStop(0.6, `rgba(120,170,255,${(a * 0.35).toFixed(3)})`);
      g.addColorStop(1, 'rgba(120,170,255,0)');
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, vw, vh);
      ctx.restore();
    }
  }

  // how far above its tile bottom an animal sprite reaches, in tiles (for the tamed heart)
  const ANIMAL_TOP = { chicken: 0.95, sheep: 1.45, cow: 2.1 };
  const HEART = ['.##.##.', '#######', '#######', '.#####.', '..###..', '...#...'];
  function drawHeart(cx, bottom, ts) {
    const q = Math.max(1, Math.round(ts / 26));
    const x0 = Math.round(cx - 3.5 * q), y0 = Math.round(bottom - 6 * q);
    ctx.fillStyle = 'rgba(40,10,20,0.55)';
    ctx.fillRect(x0 - q, y0 - q, 9 * q, 8 * q);
    HEART.forEach((row, j) => {
      for (let i = 0; i < row.length; i++) {
        if (row[i] !== '#') continue;
        ctx.fillStyle = j < 2 && i > 0 && i < 3 ? '#ffd0dc' : '#ff6f9a';
        ctx.fillRect(x0 + i * q, y0 + j * q, q, q);
      }
    });
  }

  function drawNight(list, ox, oy, ts, now) {
    const light = clamp(isNum(S.clock && S.clock.light) ? S.clock.light : 1, 0, 1);
    const dark = (1 - light) * 0.84;
    const flick = (o) => 1 + Math.sin(now / 95 + o.x * 7) * 0.025 + Math.sin(now / 41 + o.y * 3) * 0.015;
    const onScreen = (cx, cy, r) => cx > -r && cy > -r && cx < vw + r && cy < vh + r;

    if (dark > 0.02) {
      nctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      nctx.globalCompositeOperation = 'source-over';
      nctx.clearRect(0, 0, vw, vh);
      nctx.fillStyle = `rgba(6,5,20,${dark.toFixed(3)})`;
      nctx.fillRect(0, 0, vw, vh);
      nctx.globalCompositeOperation = 'destination-out';
      for (const o of S.lit) {
        const cx = ox + (o.x + 0.5) * ts, cy = oy + (o.y + 0.5) * ts;
        const r = 4.6 * ts * flick(o);
        if (!onScreen(cx, cy, r)) continue;
        const g = nctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, 'rgba(0,0,0,1)');
        g.addColorStop(0.5, 'rgba(0,0,0,0.8)');
        g.addColorStop(1, 'rgba(0,0,0,0)');
        nctx.fillStyle = g;
        nctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      }
      // each awake creature carries a little circle of night sight
      for (const e of list) {
        if (e.d.asleep) continue;
        const cx = ox + (e.rx + 0.5) * ts, cy = oy + (e.ry + 0.5) * ts;
        const r = 1.9 * ts;
        if (!onScreen(cx, cy, r)) continue;
        const g = nctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, 'rgba(0,0,0,0.55)');
        g.addColorStop(1, 'rgba(0,0,0,0)');
        nctx.fillStyle = g;
        nctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      }
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(night, 0, 0);
      ctx.restore();
    }

    // warm light from fires, stronger in the dark
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const warm = 0.05 + (1 - light) * 0.2;
    for (const o of S.lit) {
      const cx = ox + (o.x + 0.5) * ts, cy = oy + (o.y + 0.5) * ts;
      const r = (dark > 0.02 ? 4 : 2.2) * ts * flick(o);
      if (!onScreen(cx, cy, r)) continue;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
      g.addColorStop(0, `rgba(255,150,60,${warm.toFixed(3)})`);
      g.addColorStop(0.45, `rgba(255,105,40,${(warm * 0.4).toFixed(3)})`);
      g.addColorStop(1, 'rgba(255,90,30,0)');
      ctx.fillStyle = g;
      ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
    ctx.restore();
  }

  /* ------------------------------------------------------- labels, bubbles */
  const wrapCache = new Map();
  function wrapText(text, maxW, maxLines) {
    const key = maxW + '|' + text;
    const hit = wrapCache.get(key);
    if (hit) return hit;
    const words = text.split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    const push = (l) => { lines.push(l); };
    for (let w of words) {
      while (ctx.measureText(w).width > maxW) {
        let i = w.length - 1;
        while (i > 1 && ctx.measureText(w.slice(0, i)).width > maxW) i--;
        if (line) { push(line); line = ''; }
        push(w.slice(0, i));
        w = w.slice(i);
      }
      const t = line ? line + ' ' + w : w;
      if (ctx.measureText(t).width > maxW && line) { push(line); line = w; } else line = t;
    }
    if (line) push(line);
    let out = lines;
    if (lines.length > maxLines) {
      out = lines.slice(0, maxLines);
      let last = out[maxLines - 1];
      while (last.length && ctx.measureText(last + '…').width > maxW) last = last.slice(0, -1);
      out[maxLines - 1] = last.trimEnd() + '…';
    }
    if (wrapCache.size > 400) wrapCache.clear();
    wrapCache.set(key, out);
    return out;
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  const BUBBLE_FONT = `500 12px ${SANS}`;
  const LABEL_FONT = `650 11px ${SANS}`;

  /** Wraps speech (max ~140 chars shown) and returns its box size. */
  function measureBubble(raw) {
    let text = String(raw).replace(/\s+/g, ' ').trim();
    if (text.length > 140) text = text.slice(0, 139).trimEnd() + '…';
    ctx.font = BUBBLE_FONT;
    const pad = 8, lh = 15, maxW = 196;
    const lines = wrapText(text, maxW - pad * 2, 5);
    let tw = 0;
    for (const l of lines) tw = Math.max(tw, ctx.measureText(l).width);
    return { lines, pad, lh, w: Math.ceil(tw + pad * 2), h: lines.length * lh + pad * 2 - 3 };
  }

  function paintBubble(B) {
    const { b, rect, cx, anchor } = B;
    const { x, y, w, h } = rect;
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.45)';
    ctx.shadowBlur = 10;
    ctx.shadowOffsetY = 3;
    ctx.fillStyle = '#ece4d6';
    roundRect(x, y, w, h, 6);
    ctx.fill();
    ctx.restore();
    const tx = clamp(cx, x + 10, x + w - 10);
    ctx.fillStyle = '#ece4d6';
    if (anchor - (y + h) > 9) {
      // stacked above another bubble: a thin leader down to the speaker's name
      ctx.fillRect(Math.round(tx) - 1, y + h, 2, anchor - (y + h) - 2);
    } else {
      ctx.beginPath();
      ctx.moveTo(tx - 5, y + h - 0.5);
      ctx.lineTo(tx, y + h + 6);
      ctx.lineTo(tx + 5, y + h - 0.5);
      ctx.fill();
    }
    ctx.font = BUBBLE_FONT;
    ctx.fillStyle = '#1c1420';
    ctx.textBaseline = 'top';
    b.lines.forEach((l, i) => ctx.fillText(l, x + b.pad, y + b.pad - 1 + i * b.lh));
  }

  function drawLabel(L) {
    const { x, y, w, h } = L.rect;
    ctx.font = LABEL_FONT;
    ctx.fillStyle = L.isSel ? 'rgba(34,27,39,0.95)' : 'rgba(14,11,17,0.8)';
    roundRect(x, y, w, h, 4);
    ctx.fill();
    if (L.isSel) {
      ctx.strokeStyle = T.rgba(L.color, 0.75);
      ctx.lineWidth = 1;
      roundRect(x + 0.5, y + 0.5, w - 1, h - 1, 4);
      ctx.stroke();
    }
    ctx.fillStyle = L.color;
    ctx.fillRect(x + 6, y + 6, 5, 5);
    ctx.fillStyle = '#ebe3d5';
    ctx.textBaseline = 'middle';
    ctx.fillText(L.name, x + 15, y + h / 2 + 0.5);
  }

  function drawReticle(sx, sy, ts, h, now, color) {
    const g = 2 + Math.sin(now / 260) * 1.2;
    const L = Math.max(4, ts * 0.22);
    const x0 = sx - g, y0 = sy - g, x1 = sx + ts + g, y1 = sy + h + g;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x0, y0 + L); ctx.lineTo(x0, y0); ctx.lineTo(x0 + L, y0);
    ctx.moveTo(x1 - L, y0); ctx.lineTo(x1, y0); ctx.lineTo(x1, y0 + L);
    ctx.moveTo(x1, y1 - L); ctx.lineTo(x1, y1); ctx.lineTo(x1 - L, y1);
    ctx.moveTo(x0 + L, y1); ctx.lineTo(x0, y1); ctx.lineTo(x0, y1 - L);
    ctx.stroke();
  }

  let hoverCre = null;
  function drawOverlays(list, ox, oy, ts, now) {
    // hovered tile
    if (S.hoverPx && !drag) {
      const tx = Math.floor((S.hoverPx.x - ox) / ts), ty = Math.floor((S.hoverPx.y - oy) / ts);
      if (tx >= 0 && ty >= 0 && tx < S.width && ty < S.height) {
        ctx.strokeStyle = 'rgba(235,227,213,0.35)';
        ctx.lineWidth = 1;
        ctx.strokeRect(ox + tx * ts + 0.5, oy + ty * ts + 0.5, ts - 1, ts - 1);
      }
    }

    const showNames = S.zoom.view >= 1.9;
    const sel = S.selected;
    const p = ts / 16;
    const labels = [];

    for (const e of list) {
      const c = e.d;
      const sx = ox + e.rx * ts, sy = oy + e.ry * ts;
      if (sx < -220 || sy < -160 || sx > vw + 220 || sy > vh + 220) continue;
      const cx = sx + ts / 2;
      const isSel = c.id === sel;
      const isHover = hoverCre === e;
      const color = c.color || '#cfc6b8';
      // top of the sprite: one tile up for Kenney, about 1.6 tiles for LimeZu characters
      const head = sy + ts - SK.spriteTopTiles * ts;

      if (isSel) drawReticle(sx, head, ts, sy + ts - head, now, '#f2e9da');
      else if (isHover) drawReticle(sx, head, ts, sy + ts - head, now, 'rgba(242,233,218,0.45)');

      // low health bar
      if (isNum(c.health) && c.health < 30) {
        const bw = Math.max(10, ts * 0.7), bh = Math.max(2, Math.round(p * 1.5));
        const bx = Math.round(cx - bw / 2), by = Math.round(sy + ts + 2);
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(bx - 1, by - 1, bw + 2, bh + 2);
        ctx.fillStyle = '#e6482e';
        ctx.fillRect(bx, by, Math.max(1, bw * clamp(c.health, 0, 100) / 100), bh);
      }

      // thinking: a pulsing dot at the shoulder
      if (c.thinking && !c.asleep) {
        const r = Math.max(2.5, p * 1.6) * (1 + 0.22 * Math.sin(now / 150));
        const dx = sx + ts - Math.max(3, p * 2), dy = head + Math.max(3, p * 2);
        ctx.fillStyle = 'rgba(60,172,215,0.28)';
        ctx.beginPath(); ctx.arc(dx, dy, r * 2, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#7fd0f0';
        ctx.beginPath(); ctx.arc(dx, dy, r, 0, Math.PI * 2); ctx.fill();
      }

      // asleep: drifting z's
      if (c.asleep) {
        const base = (now / 1600 + (T.hashStr(c.id) % 100) / 100) % 1;
        ctx.textBaseline = 'alphabetic';
        for (let i = 0; i < 2; i++) {
          const k = (base + i * 0.5) % 1;
          const size = Math.round(Math.max(11, ts * 0.34) * (0.75 + k * 0.5));
          ctx.font = `700 ${size}px ${SANS}`;
          ctx.fillStyle = `rgba(201,191,230,${(Math.sin(k * Math.PI) * 0.95).toFixed(3)})`;
          ctx.fillText('z', sx + ts * 0.72 + k * ts * 0.28, head + ts * 0.18 - k * ts * 0.55);
        }
      }

      const say = c.say && String(c.say).trim();
      if (showNames || isSel || isHover || say) {
        labels.push({ name: String(c.name || c.id), color, cx, bottom: Math.round(head - 3), isSel, say, pri: isSel ? 3 : say || isHover ? 2 : 0 });
      }
    }

    // Name labels: important ones first; plain labels that would collide are skipped.
    labels.sort((a, b) => b.pri - a.pri);
    ctx.font = LABEL_FONT;
    const placed = [];
    for (const L of labels) {
      const w = Math.ceil(ctx.measureText(L.name).width + 20), h = 17;
      L.rect = { x: Math.round(L.cx - w / 2), y: L.bottom - h, w, h };
      if (L.pri === 0 && placed.some((o) => overlaps(o.rect, L.rect, 1))) continue;
      placed.push(L);
    }
    for (let i = placed.length - 1; i >= 0; i--) drawLabel(placed[i]);

    // Speech bubbles go above everything else and stack instead of overlapping.
    const bubbles = [];
    for (const L of placed) {
      if (!L.say) continue;
      const b = measureBubble(L.say);
      const x = clamp(Math.round(L.cx - b.w / 2), 6, Math.max(6, vw - b.w - 6));
      let y = L.rect.y - 7 - b.h;
      for (let k = 0; k < 8; k++) {
        const r = { x, y, w: b.w, h: b.h };
        const hit = bubbles.find((o) => overlaps(o.rect, r, 3));
        if (!hit) break;
        y = hit.rect.y - b.h - 6;
      }
      bubbles.push({ b, rect: { x, y, w: b.w, h: b.h }, cx: L.cx, anchor: L.rect.y });
    }
    for (let i = bubbles.length - 1; i >= 0; i--) paintBubble(bubbles[i]);
  }

  function overlaps(a, b, pad) {
    return a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;
  }

  /* ---------------------------------------------------------------- input */
  let drag = null;

  function creatureAt(px, py) {
    const { ox, oy, ts } = view;
    let best = null, bestD = Infinity;
    const half = SK.spriteTopTiles / 2;
    for (const e of S.cres.values()) {
      const cx = ox + (e.rx + 0.5) * ts, cy = oy + (e.ry + 1 - half) * ts;
      const dx = Math.abs(px - cx), dy = Math.abs(py - cy);
      if (dx > ts * 0.55 + 4 || dy > ts * half + 4) continue;
      const d = dx + dy * 0.5;
      if (d < bestD) { best = e; bestD = d; }
    }
    return best;
  }

  function updateHover() {
    const info = $('hover-info');
    if (!S.hoverPx || !S.loaded) { hoverCre = null; setHTML(info, ''); canvas.classList.remove('is-pointing'); return; }
    const { ox, oy, ts } = view;
    hoverCre = drag && drag.moved ? null : creatureAt(S.hoverPx.x, S.hoverPx.y);
    canvas.classList.toggle('is-pointing', !!hoverCre);
    const tx = Math.floor((S.hoverPx.x - ox) / ts), ty = Math.floor((S.hoverPx.y - oy) / ts);
    if (tx < 0 || ty < 0 || tx >= S.width || ty >= S.height) { setHTML(info, ''); return; }
    const code = (S.tiles[ty] || '')[tx] || 'g';
    const parts = [`<span class="hv-k">${tx},${ty}</span>`, `<span class="hv-v">${esc(T.terrainName(code))}</span>`];
    for (const o of S.objAt.get(tx + ',' + ty) || []) {
      let s = o.label ? `${T.objectName(o.kind)} “${o.label}”` : T.objectName(o.kind);
      if (o.kind === 'campfire') s += o.lit === false ? ' (out)' : ' (lit)';
      if (o.kind === 'crop') s = `${o.crop || 'wheat'} (${['sprouting', 'growing', 'ripe'][clamp(o.stage | 0, 0, 2)]})`;
      if (o.tamed_by) s += ` · tamed by ${o.tamed_by}`;
      if (o.kind === 'creation') s = `“${o.label || 'an invention'}” (invention)${o.text ? ` · ${String(o.text).slice(0, 80)}` : ''}`;
      parts.push(`<span class="hv-v">${esc(s)}</span>`);
    }
    if (hoverCre) {
      const c = hoverCre.d;
      let s = `${c.name} · ${c.model || ''} · ${c.asleep ? 'asleep' : c.thinking ? 'thinking' : activityText(c)}`;
      if (c.holding) s += ` · holding ${itemName(c.holding)}`;
      parts.push(`<span class="hv-v" style="color:${T.readable(c.color || '#cfc6b8')}">${esc(s)}</span>`);
    }
    setHTML(info, parts.join('<span class="hv-k"> · </span>'));
  }

  function bindMap() {
    canvas.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      canvas.setPointerCapture(e.pointerId);
      drag = { x: e.clientX, y: e.clientY, cx: S.cam.x, cy: S.cam.y, moved: false };
    });
    canvas.addEventListener('pointermove', (e) => {
      const r = canvas.getBoundingClientRect();
      S.hoverPx = { x: e.clientX - r.left, y: e.clientY - r.top };
      if (drag) {
        let dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) > 4) {
          drag.moved = true;
          canvas.classList.add('is-dragging');
          if (S.following) { S.following = false; renderFollow(); }
          S.zoom.anchor = null;
          drag.x = e.clientX; drag.y = e.clientY; drag.cx = S.cam.x; drag.cy = S.cam.y;
          dx = 0; dy = 0;
        }
        if (drag.moved) {
          S.cam.x = drag.cx - dx / view.ts;
          S.cam.y = drag.cy - dy / view.ts;
          clampCam();
        }
      }
      updateHover();
    });
    const end = (e) => {
      if (!drag) return;
      const wasClick = !drag.moved;
      drag = null;
      canvas.classList.remove('is-dragging');
      if (wasClick && e.type === 'pointerup' && e.altKey && !S.voice.disabled) {
        const r = canvas.getBoundingClientRect();
        const tx = Math.floor((e.clientX - r.left - view.ox) / view.ts), ty = Math.floor((e.clientY - r.top - view.oy) / view.ts);
        if (tx >= 0 && ty >= 0 && tx < S.width && ty < S.height) { S.voice.target = { x: tx, y: ty }; openVoice(true); }
        updateHover();
        return;
      }
      if (wasClick && e.type === 'pointerup') {
        const r = canvas.getBoundingClientRect();
        const hit = creatureAt(e.clientX - r.left, e.clientY - r.top);
        if (hit) {
          select(hit.d.id, true);
          showTab('creature');
          if (document.body.classList.contains('panel-collapsed') && window.innerWidth > 900) setPanel(true);
        }
      }
      updateHover();
    };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
    canvas.addEventListener('pointerleave', () => { if (!drag) { S.hoverPx = null; updateHover(); } });

    let wheelAcc = 0, wheelAt = 0;
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const now = performance.now();
      if (now - wheelAt > 250) wheelAcc = 0;
      wheelAt = now;
      wheelAcc += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      if (Math.abs(wheelAcc) < 50) return;
      const dir = wheelAcc < 0 ? 1 : -1;
      wheelAcc = 0;
      const r = canvas.getBoundingClientRect();
      zoomStep(dir, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    new ResizeObserver(resize).observe(canvas);
    window.addEventListener('resize', resize);
  }

  function bindUI() {
    for (const el of document.querySelectorAll('[data-ico]')) setIco(el, el.dataset.ico);

    document.querySelector('.tabs').addEventListener('click', (e) => {
      const b = e.target.closest('.tab');
      if (b) showTab(b.dataset.tab);
    });
    document.querySelector('.tabs').addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const tabs = [...document.querySelectorAll('.tab')];
      const i = tabs.findIndex((t) => t.dataset.tab === S.tab);
      const n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      showTab(n.dataset.tab);
      n.focus();
    });

    $('panel-toggle').addEventListener('click', () => setPanel(document.body.classList.contains('panel-collapsed')));
    $('voice-btn').addEventListener('click', () => openVoice(!S.voice.open));
    $('voice-form').addEventListener('submit', (e) => { e.preventDefault(); sendVoice(); });
    $('voice-input').addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); openVoice(false); } });
    $('voice-scope').addEventListener('click', (e) => {
      if (e.target.closest('[data-everyone]')) { S.voice.target = null; renderVoiceScope(); $('voice-input').focus(); }
    });
    document.addEventListener('pointerdown', (e) => {
      if (S.voice.open && !e.target.closest('.voice') && !(e.target === canvas && e.altKey)) openVoice(false);
    });
    $('conn').addEventListener('click', retryNow);
    $('follow-stop').addEventListener('click', () => { S.following = false; renderFollow(); });
    $('cre-locate').addEventListener('click', () => { if (S.selected) { S.following = true; renderFollow(); } });
    for (const b of document.querySelectorAll('[data-zoom]')) {
      b.addEventListener('click', () => zoomStep(+b.dataset.zoom, null, null));
    }

    $('roster').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-id]');
      if (b) select(b.dataset.id, true);
    });

    $('tab-chronicle').addEventListener('scroll', () => {
      const pane = $('tab-chronicle');
      if (pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80) $('chron-jump').hidden = true;
    });
    $('chron-jump').addEventListener('click', () => {
      const pane = $('tab-chronicle');
      pane.scrollTo({ top: pane.scrollHeight, behavior: 'smooth' });
      $('chron-jump').hidden = true;
    });

    $('feed').addEventListener('click', (e) => {
      const li = e.target.closest('.ev.has-target');
      if (!li) return;
      if (li.dataset.chron) { showTab('chronicle'); return; }
      if (li.dataset.actor && S.cres.has(li.dataset.actor)) { select(li.dataset.actor, true); return; }
      if (li.dataset.x != null) {
        S.following = false;
        renderFollow();
        S.cam.x = +li.dataset.x + 0.5;
        S.cam.y = +li.dataset.y + 0.5;
      }
    });

    window.addEventListener('keydown', (e) => {
      if (e.target && (e.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))) return;
      if (e.metaKey || e.ctrlKey) return;
      if (e.key === 'Escape' && S.voice.open) {
        openVoice(false);
      } else if ((e.key === 'v' || e.key === 'V') && !S.voice.disabled) {
        e.preventDefault();
        openVoice(true);
      } else if (e.key === 'Escape') {
        if (S.following) { S.following = false; renderFollow(); }
        else if (S.selected) deselect();
      } else if (e.key === '\\') {
        setPanel(document.body.classList.contains('panel-collapsed'));
      } else if (e.key === '+' || e.key === '=') {
        zoomStep(1, null, null);
      } else if (e.key === '-' || e.key === '_') {
        zoomStep(-1, null, null);
      } else if (e.key.startsWith('Arrow') && (document.activeElement === canvas || document.activeElement === document.body)) {
        const step = 4;
        if (e.key === 'ArrowLeft') S.cam.x -= step;
        if (e.key === 'ArrowRight') S.cam.x += step;
        if (e.key === 'ArrowUp') S.cam.y -= step;
        if (e.key === 'ArrowDown') S.cam.y += step;
        S.following = false;
        renderFollow();
        clampCam();
        e.preventDefault();
      }
    });

    document.addEventListener('visibilitychange', () => { if (!document.hidden && S.selected) pollDetail(); });

    // once a second: connection label countdown, detail freshness
    setInterval(() => {
      if (S.loaded && performance.now() - invAt > 120000) fetchInventions();
      renderConn();
      if (S.selected) renderDetailFoot();
    }, 1000);
  }

  /* ================================================== voice from the sky */
  function openVoice(open) {
    const V = S.voice;
    if (V.disabled) open = false;
    V.open = open;
    if (!open) V.target = null;
    $('voice-pop').hidden = !open;
    $('voice-btn').setAttribute('aria-expanded', String(open));
    $('voice-btn').classList.toggle('is-open', open);
    if (open) { renderVoiceScope(); setTimeout(() => $('voice-input').focus(), 0); }
  }

  function renderVoiceScope() {
    const V = S.voice;
    $('voice-scope').innerHTML = V.target
      ? `Only creatures within ${V.radius} tiles of <b>${V.target.x}, ${V.target.y}</b> will hear it. <button type="button" data-everyone>Speak to everyone</button>`
      : 'Every awake creature will hear it. <kbd>Alt</kbd>-click the map to speak near one spot.';
  }

  let toastTimer = null;
  function toast(msg, kind) {
    const t = $('toast');
    t.textContent = msg;
    t.dataset.kind = kind || '';
    t.hidden = false;
    t.classList.remove('is-out');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.classList.add('is-out'); toastTimer = setTimeout(() => { t.hidden = true; }, 300); }, 3200);
  }

  async function sendVoice() {
    const V = S.voice;
    const input = $('voice-input');
    const text = input.value.trim();
    if (!text || V.busy) return;
    V.busy = true;
    $('voice-send').disabled = true;
    const body = { text };
    if (V.target) { body.x = V.target.x; body.y = V.target.y; body.radius = V.radius; }
    try {
      const res = await apiPost('/api/voice', body);
      const heard = Array.isArray(res && res.heard_by) ? res.heard_by : [];
      toast(heard.length ? `Heard by ${heard.length} creature${heard.length === 1 ? '' : 's'}` : 'No one was close enough to hear it', heard.length ? 'ok' : 'warn');
      $('toast').title = heard.join(', ');
      input.value = '';
      openVoice(false);
    } catch (err) {
      if (err && err.status === 403) {
        V.disabled = true;
        const b = $('voice-btn');
        b.disabled = true;
        b.title = 'Only the machine running the world server can speak into it';
        openVoice(false);
        toast('Speaking only works on the machine running the world server', 'warn');
      } else {
        toast(`Couldn’t speak (${(err && err.message) || 'error'})`, 'warn');
      }
    } finally {
      V.busy = false;
      $('voice-send').disabled = false;
    }
  }

  function drawTitle() {
    const cv = $('title-art');
    const d = window.devicePixelRatio || 1;
    const scale = d >= 1.5 ? 1.5 : 1;
    const text = 'SWARM WORLD';
    const fire = 16 * scale;
    const w = Math.ceil(fire + 8 + T.measureGlyphText(text, scale));
    const h = Math.ceil(16 * scale);
    cv.width = Math.round(w * d); cv.height = Math.round(h * d);
    cv.style.width = w + 'px'; cv.style.height = h + 'px';
    const g = cv.getContext('2d');
    g.setTransform(d, 0, 0, d, 0, 0);
    g.imageSmoothingEnabled = false;
    T.drawObject(g, { id: 'title', kind: 'campfire', x: 0, y: 0, lit: true }, 0, 0, fire, 0);
    T.drawGlyphText(g, text, fire + 8, 0, scale, '#ebe3d5');
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error('could not load ' + src));
      document.head.appendChild(s);
    });
  }

  async function boot() {
    buildFilters();
    bindUI();
    if (window.innerWidth <= 900) setPanel(false);  // the panel would cover the map
    bindMap();
    resize();
    renderVeil();
    renderCreaturePanel();
    requestAnimationFrame(frame);

    const ok = await T.load();
    if (ok) {
      T.installIconStyles(document.documentElement, window.devicePixelRatio || 1);
      drawTitle();
    }
    // World art: LimeZu when its (gitignored) assets are present, Kenney otherwise or with ?skin=kenney.
    if (params.get('skin') !== 'kenney' && window.SwarmLimeZu && await window.SwarmLimeZu.load()) SK = window.SwarmLimeZu;
    document.documentElement.dataset.skin = SK.name;
    renderCredit();
    if (DEMO) {
      try { await loadScript('demo.js'); } catch (err) {
        console.error(err);
        setText($('veil-title'), 'Demo mode failed to start');
        setText($('veil-sub'), 'demo.js could not be loaded.');
        return;
      }
    }
    connect();
  }

  // Handle for debugging from the console; the viewer itself does not use it.
  window.SwarmViewer = { state: S, select: (id) => select(id, true), deselect };

  boot();
})();
