/* Swarm World audio: Web Audio playback for sound events near the camera, plus quiet ambient music.
 * Every effect has a synthesized voice (no files, CC0 by construction). When the licensed ElvGames & Pegonthetrack
 * samples have been extracted into assets/sfx/ (scripts/extract_sfx.py; never committed) they are preferred, with
 * variation on every play. Muted until the person clicks the speaker button (browser autoplay rules); on/off and the
 * mixer (master + one volume per category) are remembered in localStorage.
 * viewer.js calls SwarmSound.tick(events, cam, clock) once per world message. */
(function () {
  'use strict';
  const KEY = 'swarmworld.sound';
  const HEARD_TILES = 26;      // beyond this distance from the view center a sound is silent
  const MAX_VOICES = 8;
  const MIN_GAP_MS = 140;      // per sound kind

  let ctx = null, master = null, musicBus = null, noiseBuf = null;
  const MUSIC_GAIN = 0.16;

  // ------------------------------------------------------------ mixer categories
  // Every sound routes to exactly one category through CATEGORY_OF (one line per sound: move it by editing its value).
  // To add a category: add it to CATEGORIES and point sounds at it. Slider 0-100; 75 is unity gain.
  const CATEGORIES = [
    { id: 'general', label: 'General', hint: 'UI clicks, discoveries, magic, the voice from the sky', def: 75 },
    { id: 'music', label: 'Music', hint: 'ambient music', def: 75 },
    { id: 'footsteps', label: 'Footsteps', hint: 'creatures walking near the camera', def: 55 },
    { id: 'speech', label: 'Speech', hint: 'creatures talking, crowd murmur', def: 60 },
    { id: 'ambience', label: 'Ambience', hint: 'river, rain, crickets, birds, animals, fire, thunder', def: 75 },
    { id: 'crafting', label: 'Crafting', hint: 'chopping, knocking, building, crafting, cooking', def: 75 },
  ];
  const CATEGORY_OF = {
    // world sound kinds (registry.SOUND_KINDS)
    chop: 'crafting', knock: 'crafting', build: 'crafting', craft: 'crafting', cook: 'crafting',
    splash: 'ambience', fire: 'ambience', thunder: 'ambience', rain: 'ambience', river: 'ambience',
    crickets: 'ambience', bird: 'ambience', animal: 'ambience',
    crowd: 'speech', say: 'speech', footsteps: 'footsteps', music: 'music',
    dance: 'general', hunt: 'general', blip: 'general',
    // world events and viewer UI cues
    discover: 'general', invent: 'general', chronicle: 'general', wish: 'general', grant: 'general', voice: 'general',
    ui_tab: 'general', ui_open: 'general', ui_ok: 'general', ui_warn: 'general', ui_send: 'general',
  };
  const categoryOf = (kind) => CATEGORY_OF[kind.startsWith('animal:') ? 'animal' : kind] || (kind.startsWith('fs_') ? 'footsteps' : 'general');
  const sliderGain = (v) => { const x = Math.min(100, Math.max(0, +v || 0)) / 100; return x * x * 1.78; };  // 75 -> ~1.0
  const buses = {};

  const DEFAULT_VOL = 0.6;
  let state = { on: false, vol: DEFAULT_VOL, music: true, mix: {} };
  try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* private mode */ }
  state.on = !!state.on;
  state.vol = Math.min(1, Math.max(0, +state.vol || 0));
  if (!state.mix || typeof state.mix !== 'object') state.mix = {};
  const mixOf = (id) => { const c = CATEGORIES.find((k) => k.id === id); return typeof state.mix[id] === 'number' && isFinite(state.mix[id]) ? state.mix[id] : (c ? c.def : 75); };
  let voices = 0;
  const lastAt = {};
  let phase = 'day';
  let pendingStart = state.on;  // remembered "on" still needs one gesture before audio may start

  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* ignore */ } }

  function ensure() {
    if (ctx) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain();
    master.connect(ctx.destination);
    for (const c of CATEGORIES) { buses[c.id] = ctx.createGain(); buses[c.id].connect(master); }
    musicBus = ctx.createGain(); musicBus.connect(buses.music);  // the music toggle fades this; the Music slider sets the category bus
    const n = ctx.sampleRate * 2;
    noiseBuf = ctx.createBuffer(1, n, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    applyVolume();
    return true;
  }

  function applyVolume() {
    if (master) master.gain.setTargetAtTime(state.on ? state.vol * state.vol : 0, ctx.currentTime, 0.03);
    if (musicBus) musicBus.gain.setTargetAtTime(state.music ? MUSIC_GAIN : 0, ctx.currentTime, 0.3);  // music fades on its own
    for (const c of CATEGORIES) if (buses[c.id]) buses[c.id].gain.setTargetAtTime(sliderGain(mixOf(c.id)), ctx.currentTime, 0.03);
  }

  // ---------------------------------------------------------------- voice helpers
  function env(g, t, a, peak, d) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(Math.max(peak, 0.0002), t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + a + d);
  }
  function osc(type, f0, f1, t, dur, peak, a, dest) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + dur);
    env(g, t, a || 0.01, peak, dur);
    o.connect(g); g.connect(dest);
    o.start(t); o.stop(t + dur + a + 0.05);
    return o;
  }
  function noise(t, dur, peak, a, filterType, f0, f1, q, dest) {
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noiseBuf; s.loop = true;
    f.type = filterType; f.Q.value = q || 0.7;
    f.frequency.setValueAtTime(f0, t);
    if (f1 && f1 !== f0) f.frequency.exponentialRampToValueAtTime(f1, t + dur);
    env(g, t, a || 0.005, peak, dur);
    s.connect(f); f.connect(g); g.connect(dest);
    s.start(t, Math.random()); s.stop(t + dur + a + 0.05);
  }
  const hash = (s) => { let h = 7; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h; };
  const PENT = [0, 2, 4, 7, 9];
  const hz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);

  // ---------------------------------------------------------------- one synth per SOUND_KINDS entry
  const SYNTH = {
    chop(t, o) {
      for (let i = 0; i < 2; i++) {
        const k = t + i * 0.22;
        noise(k, 0.09, 0.5, 0.002, 'lowpass', 1400, 500, 0.8, o);
        osc('sine', 170, 70, k, 0.14, 0.7, 0.002, o);
      }
    },
    knock(t, o) {
      for (let i = 0; i < 3; i++) {
        const k = t + i * 0.13;
        osc('triangle', 900 - i * 80, 420, k, 0.07, 0.5, 0.001, o);
        noise(k, 0.04, 0.25, 0.001, 'bandpass', 2500, 1800, 2, o);
      }
    },
    splash(t, o) {
      noise(t, 0.45, 0.5, 0.02, 'bandpass', 700, 2600, 1.2, o);
      osc('sine', 500, 180, t + 0.03, 0.12, 0.25, 0.005, o);
    },
    fire(t, o) {
      noise(t, 1.0, 0.07, 0.15, 'lowpass', 500, 380, 0.5, o);
      for (let i = 0; i < 7; i++) noise(t + Math.random() * 0.9, 0.025, 0.35, 0.001, 'highpass', 2500 + Math.random() * 3000, 0, 0.7, o);
    },
    thunder(t, o) {
      noise(t, 2.6, 0.9, 0.08, 'lowpass', 380, 90, 0.6, o);
      osc('sine', 60, 30, t, 2.0, 0.6, 0.05, o);
    },
    rain(t, o) { noise(t, 1.6, 0.18, 0.4, 'highpass', 1500, 0, 0.5, o); },
    river(t, o) {
      noise(t, 1.8, 0.2, 0.6, 'bandpass', 500, 900, 0.8, o);
      noise(t + 0.2, 1.5, 0.1, 0.5, 'highpass', 2200, 0, 0.5, o);
    },
    crickets(t, o) {
      for (let c = 0; c < 3; c++) {
        for (let i = 0; i < 4; i++) osc('sine', 4300 + c * 90, 0, t + c * 0.34 + i * 0.045, 0.03, 0.09, 0.004, o);
      }
    },
    bird(t, o) {
      osc('sine', 2400, 3400, t, 0.12, 0.2, 0.01, o);
      osc('sine', 3300, 2500, t + 0.15, 0.16, 0.2, 0.01, o);
    },
    animal(t, o, kind) {
      const h = hash(kind), base = 150 + (h % 7) * 55;
      if (/wolf|dog|fox/.test(kind)) { osc('sawtooth', base * 1.5, base * 3, t, 0.9, 0.12, 0.2, lp(o, 700)); osc('sawtooth', base * 3, base * 2, t + 0.9, 0.7, 0.1, 0.05, lp(o, 700)); return; }
      if (/cow|ox|bull|boar|pig/.test(kind)) { osc('sawtooth', base * 0.7, base * 0.55, t, 0.9, 0.14, 0.12, lp(o, 500)); return; }
      if (/chick|hen|duck|goose|bird/.test(kind)) { for (let i = 0; i < 3; i++) osc('square', 700 + i * 90, 500, t + i * 0.11, 0.07, 0.07, 0.005, lp(o, 1800)); return; }
      osc('triangle', base * 1.6, base * 1.1, t, 0.45, 0.2, 0.04, o);
      osc('triangle', base * 1.2, base * 1.5, t + 0.5, 0.35, 0.16, 0.04, o);
    },
    crowd(t, o) {
      for (let i = 0; i < 4; i++) noise(t + i * 0.28, 0.3, 0.16, 0.08, 'bandpass', 380 + (i % 3) * 170, 300 + (i % 2) * 260, 3, o);
    },
    footsteps(t, o) {
      for (let i = 0; i < 3; i++) noise(t + i * 0.2, 0.08, 0.3, 0.003, 'lowpass', 700, 300, 0.7, o);
    },
    build(t, o) {
      for (let i = 0; i < 2; i++) {
        osc('sine', 230, 120, t + i * 0.3, 0.12, 0.6, 0.002, o);
        noise(t + i * 0.3, 0.06, 0.3, 0.001, 'bandpass', 1500, 900, 1.5, o);
      }
    },
    music(t, o) {
      [0, 2, 4, 7].forEach((s, i) => osc('triangle', hz(72 + PENT[(s + i) % 5]), 0, t + i * 0.16, 0.5, 0.2, 0.01, o));
    },
    dance(t, o) {
      [0, 4, 2, 4, 3, 4].forEach((s, i) => osc('square', hz(67 + PENT[s % 5] + (i % 2 ? 12 : 0)), 0, t + i * 0.12, 0.12, 0.07, 0.005, lp(o, 2200)));
    },
    hunt(t, o) {
      osc('sine', 110, 55, t, 0.25, 0.7, 0.005, o);
      osc('sine', 110, 55, t + 0.3, 0.25, 0.6, 0.005, o);
      noise(t + 0.6, 0.2, 0.2, 0.02, 'bandpass', 900, 400, 1, o);
    },
    blip(t, o) { osc('sine', 660, 440, t, 0.12, 0.2, 0.01, o); },
  };
  function lp(dest, f) {
    const b = ctx.createBiquadFilter();
    b.type = 'lowpass'; b.frequency.value = f; b.connect(dest);
    return b;
  }

  // ---------------------------------------------------------------- samples (optional; assets/sfx/manifest.json)
  const SFX_DIR = 'assets/sfx/';
  // The public page loads its scripts as name.js?v=<version>; the files under assets/ then carry the same ?v=, so the
  // edge keeps them for good. The private viewer's script URLs have no version, and neither do its assets.
  const VQ = (() => {
    const m = /\?(v=[\w-]+)$/.exec((document.currentScript && document.currentScript.getAttribute('src')) || '');
    return m ? '?' + m[1] : '';
  })();
  // loudness trim per sample key (the packs differ in level); anything not listed plays at 1
  const SAMPLE_TRIM = {
    chop: 1.5, knock: 1.5, build: 1.0, craft: 0.9, splash: 0.9, cook: 1.2, discover: 0.5, invent: 0.5, chronicle: 0.5,
    wish: 0.75, grant: 0.75, voice: 0.5, ui_tab: 0.5, ui_open: 0.4, ui_ok: 0.5, ui_warn: 0.4, ui_send: 0.5,
    fs_grass: 1, fs_dirt: 0.8, fs_sand: 1.6, fs_gravel: 1, fs_stone: 0.7, fs_wood: 1, fs_water: 0.9,
  };
  const KEY_GAP_MS = { discover: 6000, invent: 6000, chronicle: 8000, wish: 2500, grant: 2500, voice: 1500, craft: 1200, cook: 2500,
    ui_tab: 60, ui_open: 120, ui_ok: 250, ui_warn: 250, ui_send: 200 };
  let manifest = null;            // key -> [files]
  // Decoded audio is big, so it is lazy: a key's pool (a random handful of its files) is fetched and decoded on first
  // use, and dropped again when the key has not been used for a while (the next use picks a fresh handful).
  const POOL_SIZE = 8;            // decoded variants kept per key
  const IDLE_DROP_MS = 4 * 60 * 1000;
  const pools = new Map();        // key -> { files: [chosen], bufs: Map(file -> AudioBuffer), used: ms }
  const recent = {};              // key -> the last two files played (never repeated back to back)
  let decodedBytes = 0;

  function loadManifest() {
    try {
      fetch(SFX_DIR + 'manifest.json' + VQ, { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : null)).then((m) => {
        if (m && m.sounds && typeof m.sounds === 'object') {
          manifest = m.sounds;
          document.dispatchEvent(new CustomEvent('swarmsound-samples', { detail: { credit: m.credit || '' } }));
        }
      }).catch(() => {});
    } catch (e) { /* no fetch */ }
  }
  function poolFor(key) {
    let p = pools.get(key);
    if (p) { p.used = performance.now(); return p; }
    const all = (manifest && manifest[key]) || [];
    if (!all.length || !ctx) return null;
    const files = all.slice();
    for (let i = files.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; [files[i], files[j]] = [files[j], files[i]]; }
    p = { files: files.slice(0, POOL_SIZE), bufs: new Map(), used: performance.now() };
    pools.set(key, p);
    p.files.forEach(async (f) => {   // all of the pool at once: a handful of small files
      try {
        const r = await fetch(SFX_DIR + f + VQ);
        if (!r.ok) return;
        const buf = await ctx.decodeAudioData(await r.arrayBuffer());
        if (pools.get(key) === p) { p.bufs.set(f, buf); decodedBytes += buf.length * buf.numberOfChannels * 4; }
      } catch (e) { /* unreadable sample: the key plays what did load, else synth */ }
    });
    return p;
  }
  function dropIdle() {
    const now = performance.now();
    for (const [key, p] of pools) {
      if (now - p.used < IDLE_DROP_MS) continue;
      for (const b of p.bufs.values()) decodedBytes -= b.length * b.numberOfChannels * 4;
      pools.delete(key); delete recent[key];
    }
  }
  setInterval(dropIdle, 60 * 1000);
  function pick(key) {
    const p = poolFor(key);
    if (!p) return null;
    const files = p.files.filter((f) => p.bufs.has(f));
    if (!files.length) return null;
    const r = recent[key] || (recent[key] = []);
    let pool = files.filter((f) => !r.includes(f));
    if (!pool.length) pool = files.filter((f) => f !== r[r.length - 1]);
    if (!pool.length) pool = files;
    const f = pool[(Math.random() * pool.length) | 0];
    r.push(f);
    if (r.length > 2) r.shift();
    return p.bufs.get(f);
  }
  const jit = (amt) => 1 + (Math.random() * 2 - 1) * amt;
  /** Play a varied sample for key into its category bus; false when there is none loaded. */
  function playSample(key, gain, o) {
    o = o || {};
    const buf = pick(key);
    if (!buf) return false;
    const src = ctx.createBufferSource(), g = ctx.createGain();
    src.buffer = buf;
    src.playbackRate.value = (o.rate || 1) * jit(o.rateJit == null ? 0.06 : o.rateJit);
    g.gain.value = gain * (SAMPLE_TRIM[key] || 1) * jit(o.gainJit == null ? 0.15 : o.gainJit);
    let out = g;
    if (o.lowpass) { const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = o.lowpass; g.connect(f); out = f; }
    src.connect(g); out.connect(buses[categoryOf(key)] || buses.general);
    src.start(ctx.currentTime + 0.005 + Math.random() * 0.03);  // tiny start jitter
    voices++;
    src.onended = () => { voices--; try { out.disconnect(); } catch (e) { /* gone */ } };
    return true;
  }
  const live = () => !!ctx && state.on && ctx.state === 'running';
  const keyReady = (key, gap) => { const now = performance.now(); if (now - (lastAt[key] || 0) < gap) return false; lastAt[key] = now; return true; };

  /** World sound kinds that have a sampled voice. */
  const SAMPLED = { chop: 'chop', knock: 'knock', build: 'build', splash: 'splash' };
  let clientSteps = 0;   // ms of the last client-generated step: while steps are generated here the world's own "footsteps" sound is skipped

  function play(kind, gain) {
    if (!live()) return;
    const sub = kind.startsWith('animal:') ? kind.slice(7) : '';
    const name = sub ? 'animal' : (SYNTH[kind] ? kind : 'blip');
    const now = performance.now();
    if (now - (lastAt[kind] || 0) < MIN_GAP_MS || voices >= MAX_VOICES) return;
    lastAt[kind] = now;
    if (kind === 'footsteps') {  // never doubles the viewer's own steps: skipped while those are active, else a quiet distant step
      if (now - clientSteps < 4000) return;
      playSample('fs_dirt', gain * FS_BASE * 0.8, { rateJit: 0.1, gainJit: 0.3, lowpass: 4200 });
      return;
    }
    if (SAMPLED[kind] && playSample(SAMPLED[kind], gain)) return;
    const g = ctx.createGain();
    g.gain.value = gain * 0.9;
    g.connect(buses[categoryOf(kind)] || buses.general);
    voices++;
    try { SYNTH[name](ctx.currentTime + 0.02, g, sub); } catch (e) { /* a bad voice must not break the viewer */ }
    setTimeout(() => { voices--; try { g.disconnect(); } catch (e) { /* gone */ } }, 3200);
  }

  /** A sampled cue (events, viewer UI): quiet and only when sound is on; silent if the samples are absent. */
  function cue(key, gain) {
    if (!live() || voices >= MAX_VOICES + 4 || !keyReady(key, KEY_GAP_MS[key] || 100)) return;
    playSample(key, gain == null ? 1 : gain);
  }

  // ---------------------------------------------------------------- speech: a soft voice-like babble per say event
  function speak(actor, text, gain) {
    if (!live() || voices >= MAX_VOICES || !keyReady('say', 350)) return;
    const h = hash(String(actor || '?')), t0 = ctx.currentTime + 0.03;
    const base = 105 + (h % 90) * (h % 2 ? 1.6 : 1);          // each speaker has their own pitch
    const n = Math.max(2, Math.min(6, Math.round(String(text || '').length / 14) + 1 + ((Math.random() * 2) | 0)));
    const out = ctx.createGain(); out.gain.value = gain * 0.5; out.connect(buses.speech);
    let t = t0;
    for (let i = 0; i < n; i++) {
      const dur = 0.07 + Math.random() * 0.07, f0 = base * jit(0.18);
      const o = ctx.createOscillator(), g = ctx.createGain(), f1 = ctx.createBiquadFilter(), f2 = ctx.createBiquadFilter();
      o.type = 'sawtooth'; o.frequency.setValueAtTime(f0, t); o.frequency.linearRampToValueAtTime(f0 * jit(0.12), t + dur);
      f1.type = 'bandpass'; f1.frequency.value = 350 + Math.random() * 450; f1.Q.value = 4;   // vowel-ish formants
      f2.type = 'bandpass'; f2.frequency.value = 1100 + Math.random() * 1000; f2.Q.value = 5;
      env(g, t, 0.015, 0.45 * jit(0.3), dur);
      o.connect(f1); o.connect(f2); f1.connect(g); f2.connect(g); g.connect(out);
      o.start(t); o.stop(t + dur + 0.06);
      t += dur + 0.03 + Math.random() * 0.07;
    }
    voices++;
    setTimeout(() => { voices--; try { out.disconnect(); } catch (e) { /* gone */ } }, (t - t0) * 1000 + 400);
  }

  // ---------------------------------------------------------------- footsteps (generated from creatures that walk)
  const FS_BASE = 0.16;          // far below every other sound (those play at about 0.4-1.0)
  const FS_HEARD = 13;           // tiles from the view center
  const FS_MIN_ZOOM = 1.5;       // none when zoomed further out
  const FS_MAX_PER_SEC = 4;      // the whole crowd together
  const walkers = new Map();     // creature id -> { x, y, acc, next, rate, side }
  const stepTimes = [];

  /** viewer.js calls this each frame for every creature that is moving: its smoothed tile position and the surface
   * key ('grass', 'dirt', 'sand', 'gravel', 'stone', 'wood', 'water') under it. */
  function step(id, x, y, surface, cam, zoom) {
    let w = walkers.get(id);
    if (!w) { w = { x, y, acc: 0, next: 0.5 + Math.random() * 0.8, rate: jit(0.05), side: 0 }; walkers.set(id, w); }
    const ds = Math.hypot(x - w.x, y - w.y);
    w.x = x; w.y = y;
    if (ds > 1.5) { w.acc = 0; return; }   // a jump, not a walk
    w.acc += ds;
    if (w.acc < w.next) return;
    w.acc -= w.next;
    w.next = 0.85 + Math.random() * 0.5;   // a stride is a little different each time
    if (!live() || zoom < FS_MIN_ZOOM || voices >= MAX_VOICES + 2) return;
    const d = cam ? Math.hypot(x - cam.x, y - cam.y) : 0;
    if (d > FS_HEARD) return;
    const now = performance.now();
    while (stepTimes.length && now - stepTimes[0] > 1000) stepTimes.shift();
    if (stepTimes.length >= FS_MAX_PER_SEC) return;
    const crowd = 1 / (1 + 0.25 * stepTimes.length);   // many steppers blur into a softer murmur
    stepTimes.push(now);
    clientSteps = now;
    w.side ^= 1;
    const key = 'fs_' + (surface || 'grass');
    const gain = FS_BASE * crowd * (w.side ? 1 : 0.85) / (1 + d / 5) * Math.min(1, zoom / 3 + 0.4);
    playSample(key, gain, { rate: w.rate, rateJit: 0.08, gainJit: 0.3, lowpass: 5200 });
  }
  /** Cheap gate for viewer.js: false when footsteps would be inaudible or silenced, so it can skip the work. */
  function wantsSteps(zoom) {
    return !!manifest && live() && !pendingStart && !document.hidden && zoom >= FS_MIN_ZOOM && state.vol > 0 && mixOf('footsteps') > 0;
  }
  function forgetWalkers(alive) { if (walkers.size > 200) for (const id of walkers.keys()) if (!alive.has(id)) walkers.delete(id); }

  // ---------------------------------------------------------------- ambient music (generative: no loop seam)
  const MUSIC = {
    day: { root: 60, scale: [0, 2, 4, 7, 9], gap: [2.2, 5.0], oct: [0, 12], type: 'triangle', vol: 0.5 },
    night: { root: 57, scale: [0, 3, 5, 7, 10], gap: [3.5, 7.5], oct: [-12, 0], type: 'sine', vol: 0.45 },
  };
  let musicTimer = null, nextNote = 0, padNodes = null, padFor = '';
  const variant = () => (phase === 'night' || phase === 'dusk' ? 'night' : 'day');

  function setPad() {
    const v = variant();
    if (padFor === v || !ctx) return;
    padFor = v;
    const m = MUSIC[v], t = ctx.currentTime;
    const old = padNodes;
    if (old) { old.g.gain.cancelScheduledValues(t); old.g.gain.setValueAtTime(old.g.gain.value, t); old.g.gain.linearRampToValueAtTime(0, t + 4); setTimeout(() => old.stop(), 4500); }
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.5, t + 4);
    const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = v === 'day' ? 900 : 500;
    g.connect(f); f.connect(musicBus);
    const os = [0, 7].map((s, i) => {
      const o = ctx.createOscillator();
      o.type = 'sine'; o.frequency.value = hz(m.root - 12 + s); o.detune.value = i ? 6 : -6;
      const og = ctx.createGain(); og.gain.value = 0.35;
      o.connect(og); og.connect(g); o.start();
      return o;
    });
    padNodes = { g, stop() { os.forEach((o) => { try { o.stop(); } catch (e) { /* stopped */ } }); } };
  }
  function musicLoop() {
    if (!ctx || !state.on || !state.music || ctx.state !== 'running') return;
    setPad();
    const m = MUSIC[variant()];
    while (nextNote < ctx.currentTime + 0.6) {
      if (nextNote < ctx.currentTime) nextNote = ctx.currentTime + 0.1;
      const note = m.root + m.oct[(Math.random() * m.oct.length) | 0] + m.scale[(Math.random() * m.scale.length) | 0];
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = m.type; o.frequency.value = hz(note);
      const dur = 2.4;
      g.gain.setValueAtTime(0.0001, nextNote);
      g.gain.exponentialRampToValueAtTime(m.vol * 0.5, nextNote + 0.06);
      g.gain.exponentialRampToValueAtTime(0.0001, nextNote + dur);
      o.connect(g); g.connect(musicBus);
      o.start(nextNote); o.stop(nextNote + dur + 0.1);
      nextNote += m.gap[0] + Math.random() * (m.gap[1] - m.gap[0]);
    }
  }
  function startMusic() {
    if (musicTimer || !state.music) return;
    nextNote = 0;
    musicTimer = setInterval(musicLoop, 300);
    musicLoop();
  }
  function stopMusic() { if (musicTimer) { clearInterval(musicTimer); musicTimer = null; } }

  // ---------------------------------------------------------------- on/off, volume, UI
  const ICON_ON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19 6a8.5 8.5 0 0 1 0 12"/></svg>';
  const ICON_OFF = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 9l5 6"/><path d="M22 9l-5 6"/></svg>';

  function renderUI() {
    const b = document.getElementById('sound-btn');
    if (b) {
      const live = state.on && !pendingStart;  // a remembered "on" is silent until the first gesture
      b.innerHTML = (live ? ICON_ON : ICON_OFF) + '<span class="sr-only">Sound</span>';
      b.setAttribute('aria-pressed', live ? 'true' : 'false');
      b.title = live ? 'Mute sound (M)' : 'Turn sound on (M)';
    }
    const set = (id, val) => { const el = document.getElementById('mix-' + id), o = document.getElementById('mixv-' + id); if (el) el.value = val; if (o) o.textContent = val; };
    set('master', Math.round(state.vol * 100));
    for (const c of CATEGORIES) set(c.id, Math.round(mixOf(c.id)));
    const mb = document.getElementById('music-btn');
    if (mb) {
      mb.setAttribute('aria-pressed', state.music ? 'true' : 'false');
      mb.title = state.music ? 'Turn music off (sound effects stay on)' : 'Turn music on';
    }
  }

  function setMusic(on) {  // music has its own switch; sound effects keep playing either way
    state.music = !!on;
    save();
    applyVolume();
    if (state.music && state.on && !pendingStart && ctx && ctx.state === 'running') startMusic(); else stopMusic();
    renderUI();
  }

  function setOn(on) {
    state.on = !!on;
    save();
    pendingStart = false;
    if (state.on && ensure()) {
      applyVolume();
      const go = () => { startMusic(); };
      if (ctx.state === 'running') go(); else ctx.resume().then(go, () => {});
    } else {
      applyVolume();
      stopMusic();
      if (ctx && ctx.state === 'running') setTimeout(() => { if (!state.on && ctx) ctx.suspend(); }, 300);
    }
    renderUI();
  }

  const ICON_GEAR = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>';
  function buildMixer() {
    const btn = document.getElementById('audio-btn'), pop = document.getElementById('audio-pop');
    if (!btn || !pop) return;
    btn.innerHTML = ICON_GEAR + '<span class="sr-only">Audio settings</span>';
    const rows = [{ id: 'master', label: 'Master', hint: 'overall volume' }].concat(CATEGORIES);
    pop.innerHTML = '<div class="mix-title">Audio settings</div>' + rows.map((r) =>
      `<div class="mix-row"><label for="mix-${r.id}" title="${r.hint}">${r.label}</label>` +
      `<input id="mix-${r.id}" type="range" min="0" max="100" step="1" aria-label="${r.label} volume"><output id="mixv-${r.id}"></output></div>`).join('') +
      '<button type="button" class="mix-reset" id="mix-reset">Reset to defaults</button>';
    const set = (id, val) => {
      if (id === 'master') state.vol = val / 100; else state.mix[id] = val;
      document.getElementById('mixv-' + id).textContent = val;
      save(); applyVolume();
    };
    for (const r of rows) {
      const el = document.getElementById('mix-' + r.id);
      el.addEventListener('input', () => set(r.id, +el.value));
    }
    document.getElementById('mix-reset').addEventListener('click', () => { state.vol = DEFAULT_VOL; state.mix = {}; save(); applyVolume(); renderUI(); });
    const open = (on) => { pop.hidden = !on; btn.setAttribute('aria-expanded', String(on)); if (on) document.getElementById('mix-master').focus(); };
    btn.addEventListener('click', (e) => { e.stopPropagation(); open(pop.hidden); });
    pop.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); open(false); btn.focus(); } });
    document.addEventListener('pointerdown', (e) => { if (!pop.hidden && !pop.contains(e.target) && !btn.contains(e.target)) open(false); });
  }

  function init() {
    const b = document.getElementById('sound-btn');
    buildMixer();
    loadManifest();
    renderUI();
    if (b) b.addEventListener('click', (e) => { e.stopPropagation(); setOn(!(state.on && !pendingStart)); });
    const mb = document.getElementById('music-btn');
    if (mb) mb.addEventListener('click', (e) => { e.stopPropagation(); setMusic(!state.music); });
    window.addEventListener('keydown', (e) => {
      const tag = (e.target && e.target.tagName) || '';
      if ((e.key === 'm' || e.key === 'M') && !e.metaKey && !e.ctrlKey && !e.altKey && !/INPUT|TEXTAREA|SELECT/.test(tag) && !(e.target && e.target.closest && e.target.closest('dialog'))) setOn(!(state.on && !pendingStart));
    });
    // a remembered "on" resumes with the first gesture, as browsers require
    const first = (e) => {
      if (e.type === 'keydown' && (e.key === 'm' || e.key === 'M')) return;  // the M handler is this gesture
      if (b && e.target && b.contains(e.target)) return;                     // so is the button's own click
      if (pendingStart && state.on) setOn(true);
      window.removeEventListener('pointerdown', first, true);
      window.removeEventListener('keydown', first, true);
    };
    window.addEventListener('pointerdown', first, true);
    window.addEventListener('keydown', first, true);
    document.addEventListener('visibilitychange', () => {  // a hidden tab plays nothing
      if (!ctx) return;
      if (document.hidden) { stopMusic(); if (ctx.state === 'running') ctx.suspend(); }
      else if (state.on && !pendingStart) ctx.resume().then(startMusic, () => {});
    });
  }

  // ---------------------------------------------------------------- the hook viewer.js calls
  const cookWords = /\b(cook|bake|baked|brew|boil|roast|stew|simmer|fry|fried)/i;
  /** World events that are not sound events: celebrations, wishes, the voice, crafting, creatures talking. */
  function worldEvent(ev, cx, cy) {
    const near = isFinite(cx) && isFinite(ev.x) ? Math.hypot(ev.x - cx, ev.y - cy) : 0;
    switch (ev.kind) {
      case 'discover': case 'invent': if (near <= HEARD_TILES) cue(ev.kind, 1 / (1 + near / 14)); break;
      case 'chronicle': case 'wish': case 'grant': cue(ev.kind, ev.kind === 'chronicle' ? 0.8 : 0.7); break;  // heard anywhere: they belong to the whole world
      case 'voice': cue('voice', 1); break;
      case 'craft': if (near <= HEARD_TILES) cue(cookWords.test(ev.text || '') ? 'cook' : 'craft', 1 / (1 + near / 8)); break;
      case 'say': if (near <= 14) speak(ev.actor, ev.text, 1 / (1 + near / 5)); break;
      default: break;
    }
  }

  function tick(events, cam, clock) {
    if (clock && clock.phase) phase = clock.phase;
    if (!state.on || !ctx || ctx.state !== 'running' || !Array.isArray(events)) return;
    const cx = cam && +cam.x, cy = cam && +cam.y;
    for (const ev of events) {
      if (!ev) continue;
      if (ev.kind !== 'sound') { worldEvent(ev, cx, cy); continue; }
      const kind = String(ev.sound || 'blip');
      const d = isFinite(cx) && isFinite(ev.x) ? Math.hypot(ev.x - cx, ev.y - cy) : 0;
      if (d > HEARD_TILES) continue;
      let gain = 1 / (1 + d / 7);
      if (ev.loud) gain = Math.min(1, gain * 1.6);
      play(kind, gain);
    }
  }

  window.SwarmSound = {
    tick, setOn, get on() { return state.on; }, kinds: Object.keys(SYNTH), play, cue, step, wantsSteps, forgetWalkers,
    get decodedBytes() { return decodedBytes; },
    get samples() { return !!manifest; }, categories: CATEGORIES.map((c) => c.id),
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
