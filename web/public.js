/* Swarm World viewer: public mode.
 *
 * Stands in for the world server in the browser, like demo.js does, but with the real world: it polls the snapshot
 * documents under /public/ (live.json every few seconds, static.json when its version changes) and replays each
 * snapshot's per-tick creature paths and events as the socket messages the viewer already understands. The tab shows
 * the world one interval behind. It only ever fetches /public/ paths; the one thing it sends is the "here" check-in
 * (POST /public/here, a random id made for this page load and kept in memory) that lets the Mac count who is watching.
 */
(function () {
  'use strict';

  const SCHEMA = 1;
  const MAX_FRAMES = 16;       // the longest catch-up after a sleep (the server keeps this many ticks of trail)
  const HIDDEN_POLL_MS = 30000;
  const RETRY_MS = 1000;
  const STATIC_TRIES = 3;      // retries of a static.json that does not match the live document's version
  const HERE_PATH = '/public/here';
  const RELOAD_KEY = 'swarm-public-reloaded';

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const jsonOf = (v) => JSON.stringify(v);

  /** A random id for this page load: 16 random bytes as 32 hex chars. Never stored anywhere. */
  function makeId(getRandomValues) {
    const grv = getRandomValues || ((a) => window.crypto.getRandomValues(a));
    const bytes = grv(new Uint8Array(16));
    return Array.from(bytes, (b) => (b < 16 ? '0' : '') + b.toString(16)).join('');
  }

  /** The metrics message for a live document: its metrics, and the watching count the header shows. */
  const metricsOf = (live) => Object.assign({ type: 'metrics' }, live.metrics, { watching: live.watching });

  /* ------------------------------------------------------------------ views */
  /** The static world with a live document's changes applied: objects by id, tile rows, buildings, landmarks. */
  function viewOf(staticDoc, live) {
    live = live || {};
    const objects = new Map();
    for (const o of staticDoc.objects || []) objects.set(o.id, o);
    for (const o of live.objects_upsert || []) objects.set(o.id, o);
    for (const id of live.objects_removed || []) objects.delete(id);
    const tiles = (staticDoc.tiles || []).slice();
    const width = staticDoc.width | 0;
    for (const [x, y, t] of live.tiles || []) {
      if (!(x >= 0 && x < width && y >= 0 && y < tiles.length) || typeof t !== 'string') continue;
      const row = tiles[y];
      tiles[y] = row.slice(0, x) + t + row.slice(x + 1);
    }
    return {
      objects, tiles,
      buildings: Array.isArray(live.buildings) ? live.buildings : (staticDoc.buildings || []),
      landmarks: Array.isArray(live.landmarks) ? live.landmarks : (staticDoc.landmarks || []),
    };
  }

  function cardOf(c) {
    const card = Object.assign({}, c);
    delete card.path;
    return card;
  }

  function initMessage(staticDoc, live) {
    const view = viewOf(staticDoc, live);
    return {
      type: 'init', width: staticDoc.width, height: staticDoc.height, tiles: view.tiles,
      objects: Array.from(view.objects.values()), creatures: (live.creatures || []).map(cardOf),
      regions: staticDoc.regions, tick: live.tick, clock: live.clock, items: staticDoc.items,
      landmarks: view.landmarks, buildings: view.buildings, kinds: staticDoc.kinds, nature: staticDoc.nature,
    };
  }

  /** What changed from one view to the next, in the shape of a tick message; null means unchanged. */
  function diffViews(prev, next) {
    const upsert = [];
    for (const [id, o] of next.objects) {
      const was = prev.objects.get(id);
      if (!was || jsonOf(was) !== jsonOf(o)) upsert.push(o);
    }
    const removed = [];
    for (const id of prev.objects.keys()) if (!next.objects.has(id)) removed.push(id);
    const tiles = [];
    for (let y = 0; y < next.tiles.length; y++) {
      const a = prev.tiles[y] || '', b = next.tiles[y];
      if (a === b) continue;
      for (let x = 0; x < b.length; x++) if (a[x] !== b[x]) tiles.push([x, y, b[x]]);
    }
    const same = (a, b) => jsonOf(a) === jsonOf(b);
    return {
      objects_upsert: upsert, objects_removed: removed, tiles: tiles.length ? tiles : null,
      buildings: same(prev.buildings, next.buildings) ? null : next.buildings,
      landmarks: same(prev.landmarks, next.landmarks) ? null : next.landmarks,
    };
  }

  /** One tick message per tick since the last snapshot (at most MAX_FRAMES), creatures walking their paths. */
  function tickFrames(live, at, changes) {
    const n = clamp(live.tick - Math.max(at.tick, live.from_tick), 1, MAX_FRAMES);
    const first = live.tick - n + 1;
    const none = { objects_upsert: [], objects_removed: [], tiles: null, buildings: null, landmarks: null };
    const frames = [];
    for (let i = 0; i < n; i++) {
      frames.push(Object.assign({
        type: 'tick', tick: first + i, clock: live.clock, events: [],
        creatures: (live.creatures || []).map((c) => {
          const card = cardOf(c);
          const path = c.path;
          if (Array.isArray(path) && path.length) {
            const p = path[Math.max(0, path.length - n + i)];
            card.x = p[0];
            card.y = p[1];
          }
          return card;
        }),
      }, none));
    }
    Object.assign(frames[n - 1], changes);
    for (const e of live.events || []) {
      if (!(e.seq > at.eventSeq)) continue;
      frames[clamp(e.tick - first, 0, n - 1)].events.push(e);
    }
    return frames;
  }

  function pollDelay(o) {
    if (o.hidden) return HIDDEN_POLL_MS;
    if (o.failures > 0 || o.sameSeq) return RETRY_MS;
    return o.every * 1000 * (0.9 + 0.2 * o.rand());
  }

  /* ------------------------------------------------------------- transport */
  let current = null;   // the newest socket's documents, for api()
  let reloaded = false;

  function reloadOnce(reload) {
    let stamped = reloaded;
    try {
      if (typeof sessionStorage !== 'undefined') {
        stamped = stamped || !!sessionStorage.getItem(RELOAD_KEY);
        sessionStorage.setItem(RELOAD_KEY, '1');
      }
    } catch (e) { /* storage blocked: the in-memory flag guards */ }
    reloaded = true;
    if (!stamped) reload();
  }

  /** A socket opened with the schema this script speaks: a later schema bump in this tab may reload again. */
  function clearReloadStamp() {
    reloaded = false;
    try { if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(RELOAD_KEY); } catch (e) { /* blocked */ }
  }

  function createSocket(opts) {
    opts = opts || {};
    const doFetch = opts.fetch || ((...a) => window.fetch(...a));
    const setT = opts.setTimeout || ((f, ms) => setTimeout(f, ms));
    const clearT = opts.clearTimeout || ((h) => clearTimeout(h));
    const isHidden = opts.hidden || (() => typeof document !== 'undefined' && !!document.hidden);
    const reload = opts.reload || (() => location.reload());
    const random = opts.random || Math.random;
    const pageId = (opts.makeId || makeId)();

    const sock = {
      readyState: 0, onopen: null, onmessage: null, onclose: null, onerror: null,
      send() {},
      close() { shut(); },
    };
    const docs = { live: null, static: null, fetch: doFetch };
    let boot = null, seenSeq = -1, at = null, view = null, every = 3;
    let pollTimer = null, openTimer = null, failures = 0, unchanged = false, staticTries = 0, staticSkips = 0;
    let hereTimer = null;
    let queue = [];   // frames still to deliver: {h, msg}
    let busy = false;

    const emit = (msg) => {
      if (sock.readyState === 1 && typeof sock.onmessage === 'function') sock.onmessage({ data: jsonOf(msg) });
    };

    function shut() {
      if (sock.readyState === 3) return;
      sock.readyState = 3;
      clearT(pollTimer);
      clearT(openTimer);
      clearT(hereTimer);
      for (const q of queue) clearT(q.h);
      queue = [];
      if (typeof document !== 'undefined' && document.removeEventListener) document.removeEventListener('visibilitychange', onVisible);
      if (current === docs) current = null;
      if (typeof sock.onclose === 'function') sock.onclose({ code: 1000 });
    }

    function getJson(url, init) {
      return doFetch(url, init).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });
    }
    const getLive = () => getJson('/public/live.json', { cache: 'no-cache', headers: { Accept: 'application/json' } });
    const getStatic = (v) => getJson(`/public/static.json?v=${encodeURIComponent(v)}`, { headers: { Accept: 'application/json' } });

    /** Tell the Mac this page is open. Silent on failure: the next interval is the retry. */
    function checkIn() {
      try {
        const p = doFetch(HERE_PATH, { method: 'POST', body: jsonOf({ id: pageId }), keepalive: true, cache: 'no-store' });
        if (p && p.catch) p.catch(() => {});
      } catch (e) { /* silent */ }
    }

    /** After the first live document, then every here.every seconds: send with probability here.sample (1 when absent), not
   *  while hidden. The first check-in is gated like the rest, so a crowd arriving at once is thinned from its first request.
     *  The values are read from the latest live document each time. */
    function hereLoop() {
      if (sock.readyState === 3) return;
      const here = (docs.live && docs.live.here) || {};
      if (!isHidden() && random() < (typeof here.sample === 'number' ? here.sample : 1)) checkIn();
      const every = Number(here.every) > 0 ? Number(here.every) : 30;
      hereTimer = setT(() => hereLoop(), every * 1000);
    }

    function schedule(ms) {
      clearT(pollTimer);
      if (sock.readyState === 3) return;
      pollTimer = setT(poll, ms);
    }
    const nextDelay = () => pollDelay({ every, hidden: isHidden(), sameSeq: unchanged, failures, rand: random });

    function flushQueue() {
      const q = queue;
      queue = [];
      for (const x of q) { clearT(x.h); emit(x.msg); }
    }

    function deliver(msgs, gapMs) {
      flushQueue();
      const hidden = isHidden();
      msgs.forEach((msg, i) => {
        if (i === 0 || hidden || gapMs <= 0) { emit(msg); return; }
        const slot = Math.min(i, msgs.length - 2);   // the trailing metrics message goes out with the last frame
        const entry = { msg, h: null };
        entry.h = setT(() => {
          queue = queue.filter((x) => x !== entry);
          emit(msg);
        }, slot * gapMs);
        queue.push(entry);
      });
    }

    /** A live document that must be handled before any use: false when the socket was closed on its account. */
    function acceptable(live) {
      if (live.schema !== SCHEMA) { reloadOnce(reload); shut(); return false; }
      if (boot !== null && live.boot !== boot) { shut(); return false; }
      return true;
    }

    function fail() {
      failures++;
      if (failures >= 2) { shut(); return; }
      schedule(nextDelay());
    }

    async function open() {
      let live, st;
      try {
        live = await getLive();
        if (sock.readyState === 3) return;
        if (!acceptable(live)) return;
        st = await getStatic(live.static);
      } catch (e) {
        if (sock.readyState === 3) return;
        failures++;
        if (failures >= 2) shut(); else openTimer = setT(open, RETRY_MS);
        return;
      }
      if (sock.readyState === 3) return;
      if (!st || st.version !== live.static) {
        if (++staticTries > STATIC_TRIES) { shut(); return; }
        openTimer = setT(open, RETRY_MS);
        return;
      }
      failures = 0;
      clearReloadStamp();
      boot = live.boot;
      docs.live = live;
      docs.static = st;
      current = docs;
      every = live.every || every;
      seenSeq = live.seq;
      view = viewOf(st, live);
      at = { tick: live.tick, eventSeq: Math.max(0, ...(live.events || []).map((e) => e.seq || 0)) };
      sock.readyState = 1;
      if (typeof sock.onopen === 'function') sock.onopen({});
      const still = Object.assign({}, live, { creatures: (live.creatures || []).map(cardOf), from_tick: live.tick });
      const frame = tickFrames(still, { tick: live.tick, eventSeq: 0 }, diffViews(view, view))[0];
      emit(initMessage(st, live));
      emit(metricsOf(live));
      emit(frame);
      if (typeof document !== 'undefined' && document.addEventListener) document.addEventListener('visibilitychange', onVisible);
      schedule(nextDelay());
      hereLoop();
    }

    async function poll() {
      if (sock.readyState !== 1 || busy) return;
      busy = true;
      try {
        let live;
        try { live = await getLive(); } catch (e) { busy = false; if (sock.readyState === 1) fail(); return; }
        if (sock.readyState !== 1) return;
        if (!acceptable(live)) return;
        if (live.seq <= seenSeq) { failures = 0; unchanged = true; schedule(nextDelay()); return; }
        let st = docs.static;
        if (live.static !== st.version) {
          try { st = await getStatic(live.static); } catch (e) { fail(); return; }
          if (sock.readyState !== 1) return;
          if (!st || st.version !== live.static) {
            // a cache still serving an older static: skip this snapshot, but not forever
            if (++staticSkips > STATIC_TRIES) { shut(); return; }
            unchanged = true;
            schedule(nextDelay());
            return;
          }
        }
        failures = 0;
        staticSkips = 0;
        unchanged = false;
        const next = viewOf(st, live);
        const changes = diffViews(view, next);
        const frames = tickFrames(live, at, changes);
        every = live.every || every;
        docs.live = live;
        docs.static = st;
        seenSeq = live.seq;
        view = next;
        at = { tick: live.tick, eventSeq: Math.max(at.eventSeq, ...(live.events || []).map((e) => e.seq || 0)) };
        deliver(frames.concat([metricsOf(live)]), (every * 1000) / frames.length);
        schedule(nextDelay());
      } finally {
        busy = false;
      }
    }

    function onVisible() {
      if (!isHidden() && sock.readyState === 1) { clearT(pollTimer); poll(); }
    }

    openTimer = setT(open, 0);
    return sock;
  }

  /* ------------------------------------------------------------------ REST */
  const fetchPublic = (path) => (current && current.fetch ? current.fetch : (...a) => window.fetch(...a))(path, { cache: 'no-cache' })
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });

  function api(path) {
    const p = String(path).split('?')[0];
    const d = current;
    const notFound = () => Promise.reject(new Error('HTTP 404'));
    let m;
    if ((m = p.match(/^\/api\/creature\/([^/]+)$/))) {
      let id;
      try { id = decodeURIComponent(m[1]); } catch (e) { return notFound(); }
      return fetchPublic(`/public/creature/${encodeURIComponent(id)}.json`);
    }
    if (p === '/api/history') return fetchPublic('/public/history.json');
    if (!d || !d.live) return notFound();
    switch (p) {
      case '/api/metrics': return Promise.resolve(clone(d.live.metrics || {}));
      case '/api/society': return Promise.resolve(clone(d.live.society || {}));
      case '/api/wishes': return Promise.resolve({ can_answer: false, wishes: clone(d.live.wishes || []) });
      case '/api/inventions': return Promise.resolve(clone(d.static.inventions || []));
      case '/api/chronicle':
        return fetchPublic(`/public/chronicle.json?v=${encodeURIComponent(d.live.chronicle_version)}`)
          .catch(() => clone(d.live.chronicle || []));
      default: return notFound();
    }
  }

  function post() {
    return Promise.reject(Object.assign(new Error('HTTP 403'), { status: 403 }));
  }

  window.SwarmPublic = { SCHEMA, MAX_FRAMES, HIDDEN_POLL_MS, RETRY_MS, viewOf, initMessage, diffViews, tickFrames, pollDelay, createSocket, api, post, makeId };
})();
